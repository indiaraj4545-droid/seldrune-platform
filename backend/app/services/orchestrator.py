from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.orchestration import OrchestrationStatus, PlannedStep
from backend.app.core.tasking import AgentStatus, TERMINAL_TASK_STATUSES, TaskStatus
from backend.app.models.agent import Agent
from backend.app.models.orchestration import OrchestrationRun, OrchestrationStep
from backend.app.models.task import Task, TaskEvent


def normalize_capability(value: str) -> str:
    return "-".join(value.strip().lower().replace("_", " ").split())


def select_best_agent(
    agents: Iterable[Agent],
    required_capabilities: list[str],
) -> tuple[Agent | None, int]:
    required = {normalize_capability(item) for item in required_capabilities if item.strip()}
    if not required:
        return None, 0

    candidates: list[tuple[int, str, Agent]] = []
    for agent in agents:
        if agent.status != AgentStatus.ACTIVE.value:
            continue
        available = {normalize_capability(item) for item in agent.capabilities}
        matched = len(required & available)
        if matched == 0:
            continue
        score = round((matched / len(required)) * 100)
        candidates.append((score, agent.slug, agent))

    if not candidates:
        return None, 0

    candidates.sort(key=lambda item: (-item[0], item[1]))
    score, _, agent = candidates[0]
    return agent, score


def create_orchestration_run(
    session: Session,
    *,
    organization_id: UUID,
    created_by_user_id: UUID,
    objective: str,
    context: dict,
    plan: list[PlannedStep],
) -> OrchestrationRun:
    agents = list(
        session.scalars(
            select(Agent).where(
                Agent.organization_id == organization_id,
                Agent.status == AgentStatus.ACTIVE.value,
            )
        )
    )
    run = OrchestrationRun(
        organization_id=organization_id,
        created_by_user_id=created_by_user_id,
        objective=objective,
        context=context,
        status=OrchestrationStatus.PLANNED.value,
    )
    session.add(run)
    session.flush()

    matched_steps = 0
    for sequence, planned in enumerate(plan, start=1):
        agent, score = select_best_agent(agents, planned.required_capabilities)
        task_status = TaskStatus.ASSIGNED if agent is not None else TaskStatus.QUEUED
        task = Task(
            organization_id=organization_id,
            created_by_user_id=created_by_user_id,
            assigned_agent_id=agent.id if agent is not None else None,
            title=planned.title,
            objective=planned.objective,
            priority=planned.priority,
            status=task_status.value,
            input_data={
                "orchestration_run_id": str(run.id),
                "sequence": sequence,
                "context": context,
            },
        )
        session.add(task)
        session.flush()
        session.add(
            TaskEvent(
                organization_id=organization_id,
                task_id=task.id,
                actor_user_id=created_by_user_id,
                event_type="task.created",
                details={
                    "source": "executive-orchestrator",
                    "orchestration_run_id": str(run.id),
                    "status": task.status,
                },
            )
        )
        session.add(
            OrchestrationStep(
                orchestration_run_id=run.id,
                organization_id=organization_id,
                task_id=task.id,
                assigned_agent_id=agent.id if agent is not None else None,
                sequence=sequence,
                title=planned.title,
                objective=planned.objective,
                required_capabilities=planned.required_capabilities,
                match_score=score,
            )
        )
        if agent is not None:
            matched_steps += 1

    if matched_steps:
        run.status = OrchestrationStatus.ACTIVE.value
    run.summary = {
        "step_count": len(plan),
        "matched_steps": matched_steps,
        "unmatched_steps": len(plan) - matched_steps,
    }
    session.flush()
    return run


def refresh_orchestration_status(session: Session, run: OrchestrationRun) -> OrchestrationRun:
    task_statuses = list(
        session.scalars(
            select(Task.status)
            .join(OrchestrationStep, OrchestrationStep.task_id == Task.id)
            .where(OrchestrationStep.orchestration_run_id == run.id)
        )
    )
    if not task_statuses:
        run.status = OrchestrationStatus.PLANNED.value
        return run

    statuses = [TaskStatus(value) for value in task_statuses]
    terminal = [status for status in statuses if status in TERMINAL_TASK_STATUSES]
    succeeded = statuses.count(TaskStatus.SUCCEEDED)

    if len(terminal) == len(statuses):
        if succeeded == len(statuses):
            run.status = OrchestrationStatus.SUCCEEDED.value
        elif succeeded:
            run.status = OrchestrationStatus.PARTIAL.value
        elif all(status is TaskStatus.CANCELLED for status in statuses):
            run.status = OrchestrationStatus.CANCELLED.value
        else:
            run.status = OrchestrationStatus.FAILED.value
    elif any(status in {TaskStatus.ASSIGNED, TaskStatus.RUNNING} for status in statuses):
        run.status = OrchestrationStatus.ACTIVE.value
    else:
        run.status = OrchestrationStatus.PLANNED.value

    run.summary = {
        **(run.summary or {}),
        "succeeded_steps": succeeded,
        "terminal_steps": len(terminal),
    }
    session.flush()
    return run
