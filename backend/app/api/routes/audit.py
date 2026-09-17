from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import Select, select

from backend.app.api.dependencies import SessionDep, require_org_permission
from backend.app.core.rbac import Permission
from backend.app.models.audit import AuditLog
from backend.app.models.membership import Membership
from backend.app.schemas.audit import AuditLogPage, AuditLogPublic

router = APIRouter(prefix="/organizations/{organization_id}/audit", tags=["audit"])
audit_read_dependency = require_org_permission(Permission.AUDIT_READ)
AuditReadDep = Annotated[Membership, Depends(audit_read_dependency)]


def _apply_filters(
    statement: Select,
    *,
    action: str | None,
    resource_type: str | None,
    resource_id: str | None,
    actor_user_id: UUID | None,
    occurred_from: datetime | None,
    occurred_to: datetime | None,
) -> Select:
    if occurred_from is not None and occurred_to is not None and occurred_from > occurred_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="occurred_from must be before or equal to occurred_to",
        )
    if action is not None:
        statement = statement.where(AuditLog.action == action)
    if resource_type is not None:
        statement = statement.where(AuditLog.resource_type == resource_type)
    if resource_id is not None:
        statement = statement.where(AuditLog.resource_id == resource_id)
    if actor_user_id is not None:
        statement = statement.where(AuditLog.actor_user_id == actor_user_id)
    if occurred_from is not None:
        statement = statement.where(AuditLog.occurred_at >= occurred_from)
    if occurred_to is not None:
        statement = statement.where(AuditLog.occurred_at <= occurred_to)
    return statement


def _page(
    session: SessionDep,
    statement: Select,
    *,
    limit: int,
    offset: int,
) -> AuditLogPage:
    rows = list(
        session.scalars(
            statement.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    items = [AuditLogPublic.model_validate(row) for row in rows]
    return AuditLogPage(items=items, limit=limit, offset=offset, returned=len(items))


@router.get("", response_model=AuditLogPage)
def list_audit_logs(
    organization_id: UUID,
    _membership: AuditReadDep,
    session: SessionDep,
    action: str | None = Query(default=None, min_length=1, max_length=120),
    resource_type: str | None = Query(default=None, min_length=1, max_length=120),
    resource_id: str | None = Query(default=None, min_length=1, max_length=200),
    actor_user_id: UUID | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AuditLogPage:
    statement = select(AuditLog).where(AuditLog.organization_id == organization_id)
    statement = _apply_filters(
        statement,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )
    return _page(session, statement, limit=limit, offset=offset)


@router.get(
    "/resources/{resource_type}/{resource_id}",
    response_model=AuditLogPage,
)
def get_resource_audit_history(
    organization_id: UUID,
    resource_type: Annotated[str, Path(min_length=1, max_length=120)],
    resource_id: Annotated[str, Path(min_length=1, max_length=200)],
    _membership: AuditReadDep,
    session: SessionDep,
    action: str | None = Query(default=None, min_length=1, max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AuditLogPage:
    statement = select(AuditLog).where(
        AuditLog.organization_id == organization_id,
        AuditLog.resource_type == resource_type,
        AuditLog.resource_id == resource_id,
    )
    if action is not None:
        statement = statement.where(AuditLog.action == action)
    return _page(session, statement, limit=limit, offset=offset)


@router.get("/{audit_id}", response_model=AuditLogPublic)
def get_audit_log(
    organization_id: UUID,
    audit_id: UUID,
    _membership: AuditReadDep,
    session: SessionDep,
) -> AuditLogPublic:
    event = session.scalar(
        select(AuditLog).where(
            AuditLog.id == audit_id,
            AuditLog.organization_id == organization_id,
        )
    )
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audit log not found",
        )
    return AuditLogPublic.model_validate(event)
