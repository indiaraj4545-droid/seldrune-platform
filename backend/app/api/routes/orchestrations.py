from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from backend.app.api.dependencies import CurrentUserDep, SessionDep, require_org_permission
from backend.app.core.orchestration import PlannedStep, build_default_plan
from backend.app.core.rbac import Permission
from backend.app.models.membership import Membership
from backend.app.models.orchestration import OrchestrationRun, OrchestrationStep
from backend.app.schemas.orchestration import (
    AutonomousExecutionRequest,
    AutonomousExecutionResponse,
    OrchestrationCreate,
    OrchestrationRunPublic,
    OrchestrationStepPublic,
)
from backend.app.services.audit import record_audit
from backend.app.services.autonomous_execution import (
    AutonomousExecutionError,
    execute_orchestration_autonomously,
)
from backend.app.services.orchestrator import create_orchestration_run, refresh_orchestration_status

router = APIRouter(prefix="/organizations", tags=["orchestrations"])
orchestration_dependency = require_org_permission(Permission.AGENTS_RUN)
OrchestrationDep = Annotated[Membership, Depends(orchestration_dependency)]


def _get_run(session: SessionDep, organization_id: UUID, run_id: UUID) -> OrchestrationRun:
    run = session.scalar(
        select(OrchestrationRun).where(
            OrchestrationRun.id == run_id,
            OrchestrationRun.organization_id == organization_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orchestration not found")
    return run


def _to_public(session: SessionDep, run: OrchestrationRun) -> OrchestrationRunPublic:
    steps = list(
        session.scalars(
            select(OrchestrationStep)
            .where(OrchestrationStep.orchestration_run_id == run.id)
            .order_by(OrchestrationStep.sequence)
        )
    )
    public = OrchestrationRunPublic.model_validate(run)
    return public.model_copy(
        update={"steps": [OrchestrationStepPublic.model_validate(step) for step in steps]}
    )


@router.post(
    "/{organization_id}/orchestrations",
    response_model=OrchestrationRunPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_orchestration(
    organization_id: UUID,
    payload: OrchestrationCreate,
    _membership: OrchestrationDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> OrchestrationRunPublic:
    if payload.plan:
        plan = [
            PlannedStep(
                step.title,
                step.description,
                step.capabilities,
                step.priority,
            )
            for step in payload.plan
        ]
    else:
        plan = build_default_plan(payload.objective)

    run = create_orchestration_run(
        session,
        organization_id=organization_id,
        created_by_user_id=current_user.id,
        objective=payload.objective,
        context=payload.context,
        plan=plan,
    )
    record_audit(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="orchestration.created",
        resource_type="orchestration",
        resource_id=str(run.id),
        details={"planner_version": run.planner_version, **(run.summary or {})},
    )
    session.commit()
    session.refresh(run)
    return _to_public(session, run)


@router.get(
    "/{organization_id}/orchestrations",
    response_model=list[OrchestrationRunPublic],
)
def list_orchestrations(
    organization_id: UUID,
    _membership: OrchestrationDep,
    session: SessionDep,
) -> list[OrchestrationRunPublic]:
    runs = list(
        session.scalars(
            select(OrchestrationRun)
            .where(OrchestrationRun.organization_id == organization_id)
            .order_by(OrchestrationRun.created_at.desc())
        )
    )
    for run in runs:
        refresh_orchestration_status(session, run)
    session.commit()
    return [_to_public(session, run) for run in runs]


@router.get(
    "/{organization_id}/orchestrations/{run_id}",
    response_model=OrchestrationRunPublic,
)
def get_orchestration(
    organization_id: UUID,
    run_id: UUID,
    _membership: OrchestrationDep,
    session: SessionDep,
) -> OrchestrationRunPublic:
    run = _get_run(session, organization_id, run_id)
    refresh_orchestration_status(session, run)
    session.commit()
    session.refresh(run)
    return _to_public(session, run)


@router.post(
    "/{organization_id}/orchestrations/{run_id}/refresh",
    response_model=OrchestrationRunPublic,
)
def refresh_orchestration(
    organization_id: UUID,
    run_id: UUID,
    _membership: OrchestrationDep,
    session: SessionDep,
) -> OrchestrationRunPublic:
    run = _get_run(session, organization_id, run_id)
    refresh_orchestration_status(session, run)
    session.commit()
    session.refresh(run)
    return _to_public(session, run)


@router.post(
    "/{organization_id}/orchestrations/{run_id}/execute",
    response_model=AutonomousExecutionResponse,
)
def execute_orchestration(
    organization_id: UUID,
    run_id: UUID,
    payload: AutonomousExecutionRequest,
    _membership: OrchestrationDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> AutonomousExecutionResponse:
    run = _get_run(session, organization_id, run_id)
    try:
        report = execute_orchestration_autonomously(
            session,
            run=run,
            actor_user_id=current_user.id,
            stop_on_failure=payload.stop_on_failure,
            max_steps=payload.max_steps,
            max_retries_per_step=payload.max_retries_per_step,
            max_upstream_text_chars=payload.max_upstream_text_chars,
        )
    except AutonomousExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return AutonomousExecutionResponse(
        run=_to_public(session, run),
        execution=report,
    )
