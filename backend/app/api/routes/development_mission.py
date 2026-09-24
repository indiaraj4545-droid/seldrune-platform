from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import CurrentUserDep, SessionDep, require_org_permission
from backend.app.core.rbac import Permission
from backend.app.models.membership import Membership
from backend.app.services.development_mission import (
    build_development_mission,
    queue_parallel_ready_stages,
    sync_development_mission_task,
)


router = APIRouter(
    prefix="/organizations",
    tags=["development-mission"],
)

mission_read_dependency = require_org_permission(Permission.ORG_READ)
mission_manage_dependency = require_org_permission(Permission.ORG_MANAGE)
MissionReadDep = Annotated[Membership, Depends(mission_read_dependency)]
MissionManageDep = Annotated[Membership, Depends(mission_manage_dependency)]


@router.get("/{organization_id}/development-mission")
def get_development_mission(
    organization_id: UUID,
    _membership: MissionReadDep,
) -> dict[str, Any]:
    mission = build_development_mission()
    return {
        **mission,
        "organization_id": str(organization_id),
    }


@router.post("/{organization_id}/development-mission/sync")
def sync_development_mission(
    organization_id: UUID,
    _membership: MissionManageDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, Any]:
    task, mission, created = sync_development_mission_task(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
    )
    return {
        **mission,
        "organization_id": str(organization_id),
        "master_task_id": str(task.id),
        "master_task_status": task.status,
        "created": created,
    }


@router.post("/{organization_id}/development-mission/queue-ready")
def queue_development_mission_wave(
    organization_id: UUID,
    _membership: MissionManageDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, Any]:
    master_task, mission, _ = sync_development_mission_task(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
    )
    queued = queue_parallel_ready_stages(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        master_task=master_task,
    )
    return {
        "mission_version": mission["version"],
        "master_task_id": str(master_task.id),
        "ready_stage_ids": mission["parallel_ready_stage_ids"],
        "queued_task_ids": [str(task.id) for task in queued],
        "queued_stage_ids": [
            (task.input_data or {}).get("cognitive_mission_stage_id")
            for task in queued
        ],
        "queued_count": len(queued),
        "execution_note": (
            "Ready stages are queued in parallel. They are not marked complete "
            "until execution produces verifiable evidence."
        ),
    }
