from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.dependencies import (
    CurrentUserDep,
    SessionDep,
    require_org_permission,
)
from backend.app.api.routes.owner_commands import create_owner_command
from backend.app.core.rbac import Permission, Role
from backend.app.models.membership import Membership
from backend.app.schemas.orchestration import OrchestrationCreate, OrchestrationRunPublic
from backend.app.services.executive_briefing import build_executive_brief

router = APIRouter(prefix="/organizations", tags=["executive-brief"])
OwnerDep = Annotated[Membership, Depends(require_org_permission(Permission.ORG_MANAGE))]


def _require_owner(membership: Membership) -> None:
    if membership.role != Role.OWNER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")


@router.get("/{organization_id}/executive-brief", response_model=dict[str, Any])
def get_executive_brief(
    organization_id: UUID,
    membership: OwnerDep,
    session: SessionDep,
) -> dict[str, Any]:
    _require_owner(membership)
    return build_executive_brief(session, organization_id)


@router.post(
    "/{organization_id}/executive-brief/actions/{priority_key}",
    response_model=OrchestrationRunPublic,
    status_code=201,
)
def create_executive_priority_action(
    organization_id: UUID,
    priority_key: str,
    membership: OwnerDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> OrchestrationRunPublic:
    _require_owner(membership)
    brief = build_executive_brief(session, organization_id)
    priority = next(
        (item for item in brief["priorities"] if item.get("key") == priority_key),
        None,
    )
    if priority is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Executive priority is no longer active; refresh the brief",
        )
    action = priority.get("action") or {}
    if action.get("kind") != "owner_command" or not action.get("objective"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This priority is informational or navigational and does not create a command",
        )
    payload = OrchestrationCreate(
        objective=action["objective"],
        context={
            "executive_priority": {
                "key": priority["key"],
                "severity": priority["severity"],
                "source": priority["source"],
                "resource_id": priority.get("resource_id"),
                "title": priority["title"],
            }
        },
    )
    return create_owner_command(
        organization_id,
        payload,
        membership,
        current_user,
        session,
    )
