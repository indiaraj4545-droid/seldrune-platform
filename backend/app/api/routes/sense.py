from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.dependencies import CurrentUserDep, SessionDep, require_org_permission
from backend.app.api.routes.orchestrations import _get_run, _to_public
from backend.app.core.rbac import Permission, Role
from backend.app.models.membership import Membership
from backend.app.schemas.orchestration import (
    AutonomousExecutionRequest,
    AutonomousExecutionResponse,
)
from backend.app.services.audit import record_audit
from backend.app.services.autonomous_execution import execute_orchestration_autonomously
from backend.app.services.evidence_execution import prepare_orchestration_research
from backend.app.services.outcome_memory import record_orchestration_outcome
from backend.app.services.reflection_engine import record_execution_reflection
from backend.app.services.sense_engine import assess_orchestration

router = APIRouter(prefix="/organizations", tags=["sense-layer"])
OwnerDep = Annotated[Membership, Depends(require_org_permission(Permission.ORG_MANAGE))]


def _require_owner(membership: Membership) -> None:
    if membership.role != Role.OWNER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")


def _owner_command(run) -> dict[str, Any]:
    command = (run.context or {}).get("owner_command")
    if not command:
        raise HTTPException(status_code=404, detail="Owner command not found")
    return command


@router.get("/{organization_id}/owner-commands/{run_id}/sense", response_model=dict[str, Any])
def get_sense_assessment(
    organization_id: UUID,
    run_id: UUID,
    membership: OwnerDep,
    session: SessionDep,
) -> dict[str, Any]:
    _require_owner(membership)
    run = _get_run(session, organization_id, run_id)
    _owner_command(run)
    return assess_orchestration(session, run=run).to_dict()


@router.post(
    "/{organization_id}/owner-commands/{run_id}/sense/override",
    response_model=dict[str, Any],
)
def override_sense_review(
    organization_id: UUID,
    run_id: UUID,
    membership: OwnerDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, Any]:
    _require_owner(membership)
    run = _get_run(session, organization_id, run_id)
    command = _owner_command(run)
    assessment = assess_orchestration(session, run=run)
    if assessment.decision == "HOLD":
        raise HTTPException(
            status_code=409,
            detail="Sense HOLD cannot be overridden; resolve blockers",
        )
    run.context = {
        **(run.context or {}),
        "owner_command": {
            **command,
            "sense_override": {
                "approved": True,
                "approved_by": str(current_user.id),
                "sense_score": assessment.score,
                "sense_version": assessment.version,
            },
        },
    }
    record_audit(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="owner_command.sense_override.approved",
        resource_type="orchestration",
        resource_id=str(run.id),
        details=assessment.to_dict(),
    )
    session.commit()
    session.refresh(run)
    return {"status": "approved", "sense": assessment.to_dict()}


@router.post(
    "/{organization_id}/owner-commands/{run_id}/execute",
    response_model=AutonomousExecutionResponse,
)
def execute_owner_command_with_sense(
    organization_id: UUID,
    run_id: UUID,
    payload: AutonomousExecutionRequest,
    membership: OwnerDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> AutonomousExecutionResponse:
    _require_owner(membership)
    run = _get_run(session, organization_id, run_id)
    command = _owner_command(run)
    if command.get("approval_status") != "approved":
        raise HTTPException(status_code=409, detail="Owner command requires approval")

    prepare_orchestration_research(session, run=run, actor_user_id=current_user.id)
    assessment = assess_orchestration(
        session,
        run=run,
        actor_user_id=current_user.id,
        persist=True,
    )
    override = ((run.context or {}).get("owner_command") or {}).get("sense_override") or {}

    if assessment.decision == "HOLD":
        reason = ", ".join(assessment.blockers) or "execution blockers"
        raise HTTPException(
            status_code=409,
            detail=f"Seldrune Sense Layer HOLD ({assessment.score}/100): {reason}",
        )
    if assessment.decision == "REVIEW" and not override.get("approved"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Seldrune Sense Layer REVIEW ({assessment.score}/100): "
                "owner sense override required before execution"
            ),
        )

    report = execute_orchestration_autonomously(
        session,
        run=run,
        actor_user_id=current_user.id,
        stop_on_failure=payload.stop_on_failure,
        max_steps=payload.max_steps,
        max_retries_per_step=payload.max_retries_per_step,
        max_upstream_text_chars=payload.max_upstream_text_chars,
    )
    record_orchestration_outcome(session, run=run, actor_user_id=current_user.id)
    record_execution_reflection(session, run=run, actor_user_id=current_user.id)
    return AutonomousExecutionResponse(run=_to_public(session, run), execution=report)
