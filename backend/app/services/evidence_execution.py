from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.agent import Agent
from backend.app.models.orchestration import OrchestrationRun, OrchestrationStep
from backend.app.models.task import Task
from backend.app.services.audit import record_audit
from backend.app.services.research_runtime import collect_research_evidence


def prepare_orchestration_research(
    session: Session,
    *,
    run: OrchestrationRun,
    actor_user_id: UUID,
) -> dict[str, object]:
    steps = list(
        session.scalars(
            select(OrchestrationStep)
            .where(OrchestrationStep.orchestration_run_id == run.id)
            .order_by(OrchestrationStep.sequence)
        )
    )
    report: dict[str, object] = {
        "research_steps": 0,
        "source_count": 0,
        "approval_blocked_connectors": 0,
        "sessions": [],
        "refs": [],
    }
    sessions: list[str] = []
    refs: list[str] = []

    for step in steps:
        task = session.get(Task, step.task_id)
        if task is None or task.assigned_agent_id is None:
            continue
        agent = session.get(Agent, task.assigned_agent_id)
        if agent is None or "research" not in set(agent.capabilities or []):
            continue

        bundle = collect_research_evidence(
            session,
            task=task,
            agent=agent,
            actor_user_id=actor_user_id,
        )
        report["research_steps"] = int(report["research_steps"]) + 1
        report["source_count"] = int(report["source_count"]) + int(
            bundle.metadata.get("source_count", 0)
        )
        report["approval_blocked_connectors"] = int(
            report["approval_blocked_connectors"]
        ) + int(bundle.metadata.get("approval_blocked_connectors", 0))
        session_id = bundle.metadata.get("session_id")
        if isinstance(session_id, str):
            sessions.append(session_id)
        refs.extend(bundle.refs)

    report["sessions"] = list(dict.fromkeys(sessions))
    report["refs"] = list(dict.fromkeys(refs))
    run.summary = {**(run.summary or {}), "research_preflight": report}
    record_audit(
        session,
        organization_id=run.organization_id,
        actor_user_id=actor_user_id,
        action="orchestration.research_preflight.completed",
        resource_type="orchestration",
        resource_id=str(run.id),
        details=report,
    )
    session.commit()
    session.refresh(run)
    return report
