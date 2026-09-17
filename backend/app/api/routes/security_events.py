from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from backend.app.api.dependencies import CurrentUserDep, SessionDep, require_org_permission
from backend.app.core.rbac import Permission
from backend.app.models.membership import Membership
from backend.app.models.security_event import SecurityEvent
from backend.app.schemas.security_events import SecurityEventPage, SecurityEventPublic
from backend.app.services.audit import record_audit

router = APIRouter(prefix="/organizations/{organization_id}/security-events", tags=["security"])
SecurityReadDep = Annotated[
    Membership,
    Depends(require_org_permission(Permission.SECURITY_READ)),
]
SecurityManageDep = Annotated[
    Membership,
    Depends(require_org_permission(Permission.SECURITY_MANAGE)),
]


def _event(session: SessionDep, organization_id: UUID, event_id: UUID) -> SecurityEvent:
    event = session.scalar(
        select(SecurityEvent).where(
            SecurityEvent.id == event_id,
            SecurityEvent.organization_id == organization_id,
        )
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Security event not found")
    return event


@router.get("", response_model=SecurityEventPage)
def list_security_events(
    organization_id: UUID,
    _membership: SecurityReadDep,
    session: SessionDep,
    severity: str | None = Query(default=None, min_length=1, max_length=20),
    event_status: str | None = Query(default=None, alias="status", min_length=1, max_length=20),
    event_type: str | None = Query(default=None, min_length=1, max_length=100),
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> SecurityEventPage:
    if occurred_from is not None and occurred_to is not None and occurred_from > occurred_to:
        raise HTTPException(status_code=400, detail="occurred_from must be before occurred_to")

    filters = [SecurityEvent.organization_id == organization_id]
    if severity is not None:
        filters.append(SecurityEvent.severity == severity)
    if event_status is not None:
        filters.append(SecurityEvent.status == event_status)
    if event_type is not None:
        filters.append(SecurityEvent.event_type == event_type)
    if occurred_from is not None:
        filters.append(SecurityEvent.occurred_at >= occurred_from)
    if occurred_to is not None:
        filters.append(SecurityEvent.occurred_at <= occurred_to)

    total = session.scalar(select(func.count(SecurityEvent.id)).where(*filters)) or 0
    items = list(
        session.scalars(
            select(SecurityEvent)
            .where(*filters)
            .order_by(SecurityEvent.occurred_at.desc(), SecurityEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return SecurityEventPage(
        items=[SecurityEventPublic.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{event_id}", response_model=SecurityEventPublic)
def get_security_event(
    organization_id: UUID,
    event_id: UUID,
    _membership: SecurityReadDep,
    session: SessionDep,
) -> SecurityEventPublic:
    return SecurityEventPublic.model_validate(_event(session, organization_id, event_id))


@router.post("/{event_id}/acknowledge", response_model=SecurityEventPublic)
def acknowledge_security_event(
    organization_id: UUID,
    event_id: UUID,
    _membership: SecurityManageDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> SecurityEventPublic:
    event = _event(session, organization_id, event_id)
    if event.status == "acknowledged":
        return SecurityEventPublic.model_validate(event)

    event.status = "acknowledged"
    event.acknowledged_at = func.now()
    event.acknowledged_by_user_id = current_user.id
    record_audit(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="security_event.acknowledged",
        resource_type="security_event",
        resource_id=str(event.id),
        details={"event_type": event.event_type, "severity": event.severity},
    )
    session.commit()
    session.refresh(event)
    return SecurityEventPublic.model_validate(event)
