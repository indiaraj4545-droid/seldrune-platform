from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from backend.app.api.dependencies import SessionDep, require_org_permission
from backend.app.api.routes.executive_brief import _brief_with_lifecycle
from backend.app.core.rbac import Permission, Role
from backend.app.models.membership import Membership
from backend.app.models.orchestration import OrchestrationRun
from backend.app.services.owner_attention import build_owner_attention
from backend.app.services.owner_attention_snapshot import build_owner_attention_snapshot
from backend.app.services.owner_dashboard import build_owner_dashboard

router = APIRouter(prefix="/organizations", tags=["owner-attention"])
OwnerDep = Annotated[Membership, Depends(require_org_permission(Permission.ORG_MANAGE))]


def _require_owner(membership: Membership) -> None:
    if membership.role != Role.OWNER.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner role required",
        )


def _owner_commands(session: SessionDep, organization_id: UUID) -> list[OrchestrationRun]:
    runs = list(
        session.scalars(
            select(OrchestrationRun)
            .where(OrchestrationRun.organization_id == organization_id)
            .order_by(OrchestrationRun.created_at.desc())
        )
    )
    return [run for run in runs if (run.context or {}).get("owner_command")]


def _owner_attention_state(session: SessionDep, organization_id: UUID) -> dict[str, Any]:
    dashboard = build_owner_dashboard(session, organization_id)
    executive_brief = _brief_with_lifecycle(session, organization_id)
    commands = _owner_commands(session, organization_id)
    return build_owner_attention(
        dashboard=dashboard,
        executive_brief=executive_brief,
        commands=commands,
    )


@router.get("/{organization_id}/owner-attention", response_model=dict[str, Any])
def get_owner_attention(
    organization_id: UUID,
    membership: OwnerDep,
    session: SessionDep,
) -> dict[str, Any]:
    _require_owner(membership)
    return _owner_attention_state(session, organization_id)


@router.get("/{organization_id}/owner-attention/snapshot", response_model=dict[str, Any])
def get_owner_attention_snapshot(
    organization_id: UUID,
    membership: OwnerDep,
    session: SessionDep,
    limit: int = Query(default=5, ge=1, le=20),
    previous_fingerprint: str | None = Query(
        default=None,
        min_length=64,
        max_length=64,
        pattern="^[0-9a-fA-F]{64}$",
    ),
) -> dict[str, Any]:
    _require_owner(membership)
    attention = _owner_attention_state(session, organization_id)
    return build_owner_attention_snapshot(
        attention,
        limit=limit,
        previous_fingerprint=previous_fingerprint,
    )
