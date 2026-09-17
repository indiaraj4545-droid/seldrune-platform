from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.api.dependencies import CurrentUserDep, SessionDep, require_org_permission
from backend.app.core.rbac import Permission
from backend.app.models.membership import Membership
from backend.app.models.secret_reference import SecretReference
from backend.app.models.webhook import WebhookEndpoint, WebhookEvent
from backend.app.schemas.webhooks import (
    WebhookEndpointCreate,
    WebhookEndpointPublic,
    WebhookEndpointUpdate,
    WebhookEventPublic,
    WebhookReceipt,
)
from backend.app.services.audit import record_audit
from backend.app.services.webhook_gateway import WebhookGatewayError, get_endpoint, receive_webhook

router = APIRouter(tags=["webhooks"])
webhook_read_dependency = require_org_permission(Permission.WEBHOOKS_READ)
webhook_manage_dependency = require_org_permission(Permission.WEBHOOKS_MANAGE)
WebhookReadDep = Annotated[Membership, Depends(webhook_read_dependency)]
WebhookManageDep = Annotated[Membership, Depends(webhook_manage_dependency)]


def _get_org_endpoint(
    session: SessionDep,
    organization_id: UUID,
    endpoint_id: UUID,
) -> WebhookEndpoint:
    endpoint = session.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.organization_id == organization_id,
        )
    )
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook endpoint not found")
    return endpoint


def _validate_secret_reference(
    session: SessionDep,
    *,
    organization_id: UUID,
    secret_reference_id: UUID,
) -> None:
    reference = session.scalar(
        select(SecretReference).where(
            SecretReference.id == secret_reference_id,
            SecretReference.organization_id == organization_id,
        )
    )
    if reference is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Secret reference not found in this organization",
        )


async def _read_bounded_body(request: Request, max_bytes: int) -> bytes:
    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Webhook payload exceeds endpoint limit",
            )
        payload.extend(chunk)
    return bytes(payload)


@router.post(
    "/organizations/{organization_id}/webhooks",
    response_model=WebhookEndpointPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_webhook_endpoint(
    organization_id: UUID,
    payload: WebhookEndpointCreate,
    _membership: WebhookManageDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> WebhookEndpointPublic:
    _validate_secret_reference(
        session,
        organization_id=organization_id,
        secret_reference_id=payload.secret_reference_id,
    )
    endpoint = WebhookEndpoint(
        organization_id=organization_id,
        created_by_user_id=current_user.id,
        secret_reference_id=payload.secret_reference_id,
        name=payload.name,
        slug=payload.slug,
        allowed_event_types=payload.allowed_event_types,
        max_payload_bytes=payload.max_payload_bytes,
    )
    session.add(endpoint)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Webhook endpoint slug already exists",
        ) from exc
    record_audit(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="webhook.endpoint.created",
        resource_type="webhook_endpoint",
        resource_id=str(endpoint.id),
        details={
            "slug": endpoint.slug,
            "allowed_event_types": endpoint.allowed_event_types,
            "max_payload_bytes": endpoint.max_payload_bytes,
        },
    )
    session.commit()
    session.refresh(endpoint)
    return WebhookEndpointPublic.model_validate(endpoint)


@router.get(
    "/organizations/{organization_id}/webhooks",
    response_model=list[WebhookEndpointPublic],
)
def list_webhook_endpoints(
    organization_id: UUID,
    _membership: WebhookReadDep,
    session: SessionDep,
) -> list[WebhookEndpointPublic]:
    endpoints = list(
        session.scalars(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.organization_id == organization_id)
            .order_by(WebhookEndpoint.created_at.desc())
        )
    )
    return [WebhookEndpointPublic.model_validate(endpoint) for endpoint in endpoints]


@router.patch(
    "/organizations/{organization_id}/webhooks/{endpoint_id}",
    response_model=WebhookEndpointPublic,
)
def update_webhook_endpoint(
    organization_id: UUID,
    endpoint_id: UUID,
    payload: WebhookEndpointUpdate,
    _membership: WebhookManageDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> WebhookEndpointPublic:
    endpoint = _get_org_endpoint(session, organization_id, endpoint_id)
    changes = payload.model_dump(exclude_unset=True)
    if "secret_reference_id" in changes:
        _validate_secret_reference(
            session,
            organization_id=organization_id,
            secret_reference_id=changes["secret_reference_id"],
        )
    for field, value in changes.items():
        if hasattr(value, "value"):
            value = value.value
        setattr(endpoint, field, value)
    record_audit(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="webhook.endpoint.updated",
        resource_type="webhook_endpoint",
        resource_id=str(endpoint.id),
        details={"changed_fields": sorted(changes)},
    )
    session.commit()
    session.refresh(endpoint)
    return WebhookEndpointPublic.model_validate(endpoint)


@router.get(
    "/organizations/{organization_id}/webhook-events",
    response_model=list[WebhookEventPublic],
)
def list_webhook_events(
    organization_id: UUID,
    _membership: WebhookReadDep,
    session: SessionDep,
    endpoint_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[WebhookEventPublic]:
    statement = select(WebhookEvent).where(WebhookEvent.organization_id == organization_id)
    if endpoint_id is not None:
        statement = statement.where(WebhookEvent.endpoint_id == endpoint_id)
    events = list(
        session.scalars(statement.order_by(WebhookEvent.received_at.desc()).limit(limit))
    )
    return [WebhookEventPublic.model_validate(event) for event in events]


@router.get(
    "/organizations/{organization_id}/webhook-events/{event_id}",
    response_model=WebhookEventPublic,
)
def get_webhook_event(
    organization_id: UUID,
    event_id: UUID,
    _membership: WebhookReadDep,
    session: SessionDep,
) -> WebhookEventPublic:
    event = session.scalar(
        select(WebhookEvent).where(
            WebhookEvent.id == event_id,
            WebhookEvent.organization_id == organization_id,
        )
    )
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook event not found")
    return WebhookEventPublic.model_validate(event)


@router.post(
    "/webhooks/{endpoint_id}",
    response_model=WebhookReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_inbound_webhook(
    endpoint_id: UUID,
    request: Request,
    session: SessionDep,
    delivery_id: Annotated[str, Header(alias="X-Seldrune-Delivery")],
    event_type: Annotated[str, Header(alias="X-Seldrune-Event")],
    timestamp: Annotated[str, Header(alias="X-Seldrune-Timestamp")],
    signature: Annotated[str, Header(alias="X-Seldrune-Signature")],
) -> WebhookReceipt:
    endpoint = get_endpoint(session, endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook endpoint not found")
    body = await _read_bounded_body(request, endpoint.max_payload_bytes)
    try:
        event, duplicate = receive_webhook(
            session,
            endpoint=endpoint,
            delivery_id=delivery_id,
            event_type=event_type,
            timestamp=timestamp,
            signature=signature,
            body=body,
        )
    except WebhookGatewayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return WebhookReceipt(
        duplicate=duplicate,
        event_id=event.id,
        delivery_id=event.delivery_id,
        event_type=event.event_type,
    )
