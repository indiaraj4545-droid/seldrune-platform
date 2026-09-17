from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.membership import Membership
from backend.app.models.security_event import SecurityEvent


def record_security_event(
    session: Session,
    *,
    organization_id: UUID,
    event_type: str,
    severity: str,
    resource_type: str,
    actor_user_id: UUID | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> SecurityEvent:
    event = SecurityEvent(
        organization_id=organization_id,
        event_type=event_type,
        severity=severity,
        status="open",
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
    )
    session.add(event)
    return event


def record_user_security_event(
    session: Session,
    *,
    user_id: UUID,
    event_type: str,
    severity: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> list[SecurityEvent]:
    organization_ids = list(
        session.scalars(
            select(Membership.organization_id)
            .where(Membership.user_id == user_id)
            .order_by(Membership.organization_id)
        )
    )
    events = [
        record_security_event(
            session,
            organization_id=organization_id,
            event_type=event_type,
            severity=severity,
            actor_user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        for organization_id in organization_ids
    ]
    return events
