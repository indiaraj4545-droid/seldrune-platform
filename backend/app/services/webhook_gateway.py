from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.webhooks import WEBHOOK_REPLAY_WINDOW_SECONDS, WebhookEndpointStatus
from backend.app.models.secret_reference import SecretReference
from backend.app.models.webhook import WebhookEndpoint, WebhookEvent
from backend.app.services.audit import record_audit
from backend.app.services.secret_vault import SecretVaultError, resolve_secret

_HEADER_VALUE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
_SIGNATURE = re.compile(r"^sha256=([0-9a-fA-F]{64})$")


class WebhookGatewayError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _reject_authenticated(
    session: Session,
    *,
    endpoint: WebhookEndpoint,
    delivery_id: str,
    event_type: str,
    reason: str,
) -> None:
    record_audit(
        session,
        organization_id=endpoint.organization_id,
        actor_user_id=None,
        action="webhook.delivery.rejected",
        resource_type="webhook_endpoint",
        resource_id=str(endpoint.id),
        details={
            "delivery_id": delivery_id,
            "event_type": event_type,
            "reason": reason,
        },
    )
    session.commit()


def _runtime_secret(session: Session, endpoint: WebhookEndpoint) -> str:
    reference = session.scalar(
        select(SecretReference).where(
            SecretReference.id == endpoint.secret_reference_id,
            SecretReference.organization_id == endpoint.organization_id,
        )
    )
    if reference is None:
        raise WebhookGatewayError("Webhook runtime secret reference was not found", status_code=503)
    try:
        return resolve_secret(reference)
    except SecretVaultError as exc:
        raise WebhookGatewayError(str(exc), status_code=503) from exc


def _verify_timestamp(timestamp: str) -> int:
    try:
        value = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise WebhookGatewayError("Invalid webhook timestamp") from exc
    now = int(datetime.now(UTC).timestamp())
    if abs(now - value) > WEBHOOK_REPLAY_WINDOW_SECONDS:
        raise WebhookGatewayError("Webhook timestamp is outside the allowed replay window")
    return value


def _verify_signature(*, secret: str, timestamp: str, body: bytes, signature: str) -> None:
    match = _SIGNATURE.fullmatch(signature)
    if match is None:
        raise WebhookGatewayError("Invalid webhook signature", status_code=401)
    signed = timestamp.encode("utf-8") + b"." + body
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, match.group(1).lower()):
        raise WebhookGatewayError("Invalid webhook signature", status_code=401)


def _same_delivery(existing: WebhookEvent, *, event_type: str, payload_sha256: str) -> bool:
    return existing.event_type == event_type and existing.payload_sha256 == payload_sha256


def receive_webhook(
    session: Session,
    *,
    endpoint: WebhookEndpoint,
    delivery_id: str,
    event_type: str,
    timestamp: str,
    signature: str,
    body: bytes,
) -> tuple[WebhookEvent, bool]:
    if endpoint.status != WebhookEndpointStatus.ACTIVE.value:
        raise WebhookGatewayError("Webhook endpoint not found", status_code=404)
    if not _HEADER_VALUE.fullmatch(delivery_id):
        raise WebhookGatewayError("Invalid webhook delivery ID")
    if not _HEADER_VALUE.fullmatch(event_type):
        raise WebhookGatewayError("Invalid webhook event type")
    _verify_timestamp(timestamp)
    if len(body) > endpoint.max_payload_bytes:
        raise WebhookGatewayError("Webhook payload exceeds endpoint limit", status_code=413)

    secret = _runtime_secret(session, endpoint)
    _verify_signature(secret=secret, timestamp=timestamp, body=body, signature=signature)

    if event_type not in endpoint.allowed_event_types:
        _reject_authenticated(
            session,
            endpoint=endpoint,
            delivery_id=delivery_id,
            event_type=event_type,
            reason="event_type_not_allowed",
        )
        raise WebhookGatewayError("Webhook event type is not allowed", status_code=403)

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _reject_authenticated(
            session,
            endpoint=endpoint,
            delivery_id=delivery_id,
            event_type=event_type,
            reason="invalid_json",
        )
        raise WebhookGatewayError("Webhook payload must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        _reject_authenticated(
            session,
            endpoint=endpoint,
            delivery_id=delivery_id,
            event_type=event_type,
            reason="payload_not_object",
        )
        raise WebhookGatewayError("Webhook payload must be a JSON object")

    payload_sha256 = hashlib.sha256(body).hexdigest()
    existing = session.scalar(
        select(WebhookEvent).where(
            WebhookEvent.endpoint_id == endpoint.id,
            WebhookEvent.delivery_id == delivery_id,
        )
    )
    if existing is not None:
        if not _same_delivery(existing, event_type=event_type, payload_sha256=payload_sha256):
            _reject_authenticated(
                session,
                endpoint=endpoint,
                delivery_id=delivery_id,
                event_type=event_type,
                reason="delivery_id_conflict",
            )
            raise WebhookGatewayError(
                "Webhook delivery ID was already used for different content",
                status_code=409,
            )
        record_audit(
            session,
            organization_id=endpoint.organization_id,
            actor_user_id=None,
            action="webhook.delivery.duplicate",
            resource_type="webhook_event",
            resource_id=str(existing.id),
            details={"delivery_id": delivery_id, "event_type": event_type},
        )
        session.commit()
        return existing, True

    event = WebhookEvent(
        organization_id=endpoint.organization_id,
        endpoint_id=endpoint.id,
        delivery_id=delivery_id,
        event_type=event_type,
        payload_json=payload,
        payload_sha256=payload_sha256,
    )
    session.add(event)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        existing = session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.endpoint_id == endpoint.id,
                WebhookEvent.delivery_id == delivery_id,
            )
        )
        if existing is None:
            raise
        if not _same_delivery(existing, event_type=event_type, payload_sha256=payload_sha256):
            raise WebhookGatewayError(
                "Webhook delivery ID was already used for different content",
                status_code=409,
            ) from exc
        return existing, True

    record_audit(
        session,
        organization_id=endpoint.organization_id,
        actor_user_id=None,
        action="webhook.delivery.accepted",
        resource_type="webhook_event",
        resource_id=str(event.id),
        details={
            "endpoint_id": str(endpoint.id),
            "delivery_id": delivery_id,
            "event_type": event_type,
            "payload_sha256": event.payload_sha256,
        },
    )
    session.commit()
    session.refresh(event)
    return event, False


def get_endpoint(session: Session, endpoint_id: UUID) -> WebhookEndpoint | None:
    return session.get(WebhookEndpoint, endpoint_id)
