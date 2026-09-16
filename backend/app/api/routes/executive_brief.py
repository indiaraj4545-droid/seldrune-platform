from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.dependencies import SessionDep, require_org_permission
from backend.app.core.rbac import Permission, Role
from backend.app.models.membership import Membership
from backend.app.services.executive_briefing import build_executive_brief

router = APIRouter(prefix="/organizations", tags=["executive-brief"])
OwnerDep = Annotated[Membership, Depends(require_org_permission(Permission.ORG_MANAGE))]


@router.get("/{organization_id}/executive-brief", response_model=dict[str, Any])
def get_executive_brief(
    organization_id: UUID,
    membership: OwnerDep,
    session: SessionDep,
) -> dict[str, Any]:
    if membership.role != Role.OWNER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")
    return build_executive_brief(session, organization_id)
