from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from backend.app.api.dependencies import CurrentUserDep, SessionDep, require_org_permission
from backend.app.core.rbac import Permission
from backend.app.models.agent import Agent
from backend.app.models.membership import Membership
from backend.app.models.model_invocation import ModelInvocation
from backend.app.models.task import Task
from backend.app.schemas.agent_task import TaskPublic
from backend.app.schemas.runtime import ModelInvocationPublic
from backend.app.services.agent_runtime import AgentRuntimeError, execute_agent_task

router = APIRouter(prefix="/organizations", tags=["agent-runtime"])

agents_run_dependency = require_org_permission(Permission.AGENTS_RUN)
usage_read_dependency = require_org_permission(Permission.AUDIT_READ)
AgentsRunDep = Annotated[Membership, Depends(agents_run_dependency)]
UsageReadDep = Annotated[Membership, Depends(usage_read_dependency)]


@router.post("/{organization_id}/tasks/{task_id}/execute", response_model=TaskPublic)
def execute_task(
    organization_id: UUID,
    task_id: UUID,
    _membership: AgentsRunDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> Task:
    task = session.scalar(
        select(Task).where(
            Task.id == task_id,
            Task.organization_id == organization_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.assigned_agent_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task has no assigned agent",
        )

    agent = session.scalar(
        select(Agent).where(
            Agent.id == task.assigned_agent_id,
            Agent.organization_id == organization_id,
        )
    )
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    try:
        return execute_agent_task(
            session,
            task=task,
            agent=agent,
            actor_user_id=current_user.id,
        )
    except AgentRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get(
    "/{organization_id}/model-invocations",
    response_model=list[ModelInvocationPublic],
)
def list_model_invocations(
    organization_id: UUID,
    _membership: UsageReadDep,
    session: SessionDep,
) -> list[ModelInvocation]:
    return list(
        session.scalars(
            select(ModelInvocation)
            .where(ModelInvocation.organization_id == organization_id)
            .order_by(ModelInvocation.created_at.desc(), ModelInvocation.id)
        )
    )
