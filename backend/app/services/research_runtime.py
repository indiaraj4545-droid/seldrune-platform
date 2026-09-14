from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.research import ConnectorStatus, ResearchStatus
from backend.app.models.agent import Agent
from backend.app.models.research_connector import ResearchConnector
from backend.app.models.research_session import ResearchSession
from backend.app.models.research_source import ResearchSource
from backend.app.models.task import Task, TaskEvent
from backend.app.services.audit import record_audit
from backend.app.services.research_engine import (
    ResearchConnectorRegistry,
    ResearchEngineError,
    execute_research_session,
)


@dataclass(frozen=True)
class ResearchEvidenceBundle:
    context: str
    refs: list[str]
    metadata: dict[str, object]


def _source_context(
    sources: list[ResearchSource],
    *,
    max_chars: int,
) -> tuple[str, list[str]]:
    if not sources:
        return "", []
    lines = ["Fresh governed research evidence:"]
    refs: list[str] = []
    used = len(lines[0])
    for source in sources:
        if source.knowledge_entry_id is None:
            continue
        ref = f"knowledge:{source.knowledge_entry_id}"
        compact = " ".join(source.content.split())
        excerpt = compact[:1200] + ("..." if len(compact) > 1200 else "")
        uri = f" ({source.uri})" if source.uri else ""
        line = f"[{ref}] {source.title}{uri}: {excerpt}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        refs.append(ref)
        used += len(line)
    if not refs:
        return "", []
    lines.append("Use these sources as evidence and keep their references in the answer.")
    return "\n".join(lines), refs


def _existing_evidence(
    session: Session,
    *,
    task: Task,
    max_chars: int,
) -> ResearchEvidenceBundle | None:
    marker = (task.input_data or {}).get("research_evidence")
    if not isinstance(marker, dict) or not marker.get("session_id"):
        return None
    try:
        session_id = UUID(str(marker["session_id"]))
    except ValueError:
        return None
    sources = list(
        session.scalars(
            select(ResearchSource).where(
                ResearchSource.organization_id == task.organization_id,
                ResearchSource.research_session_id == session_id,
            )
        )
    )
    if not sources:
        return None
    context, refs = _source_context(sources, max_chars=max_chars)
    return ResearchEvidenceBundle(context=context, refs=refs, metadata=dict(marker))


def collect_research_evidence(
    session: Session,
    *,
    task: Task,
    agent: Agent,
    actor_user_id: UUID,
    max_context_chars: int = 6000,
    registry: ResearchConnectorRegistry | None = None,
) -> ResearchEvidenceBundle:
    if "research" not in set(agent.capabilities or []):
        return ResearchEvidenceBundle("", [], {"mode": "not_required"})

    existing = _existing_evidence(session, task=task, max_chars=max_context_chars)
    if existing is not None:
        return existing

    connectors = list(
        session.scalars(
            select(ResearchConnector).where(
                ResearchConnector.organization_id == task.organization_id,
                ResearchConnector.status == ConnectorStatus.ACTIVE.value,
            )
        )
    )
    safe_connectors = [item for item in connectors if item.approval_mode != "always"]
    blocked = len(connectors) - len(safe_connectors)
    if not safe_connectors:
        metadata: dict[str, object] = {
            "mode": "no_safe_connectors",
            "connector_count": len(connectors),
            "approval_blocked_connectors": blocked,
            "source_count": 0,
        }
        task.input_data = {**(task.input_data or {}), "research_evidence": metadata}
        session.commit()
        return ResearchEvidenceBundle("", [], metadata)

    research_session = ResearchSession(
        organization_id=task.organization_id,
        created_by_user_id=actor_user_id,
        title=f"Agent evidence: {task.title}"[:240],
        query=task.objective,
        objective=task.objective,
        status=ResearchStatus.DRAFT.value,
        connector_ids=[str(item.id) for item in safe_connectors],
        summary={},
    )
    session.add(research_session)
    session.flush()
    record_audit(
        session,
        organization_id=task.organization_id,
        actor_user_id=actor_user_id,
        action="agent.research.started",
        resource_type="research_session",
        resource_id=str(research_session.id),
        details={
            "task_id": str(task.id),
            "agent_id": str(agent.id),
            "connector_count": len(safe_connectors),
            "approval_blocked_connectors": blocked,
        },
    )
    session.commit()

    try:
        sources = execute_research_session(
            session,
            research_session=research_session,
            actor_user_id=actor_user_id,
            connector_ids=[item.id for item in safe_connectors],
            max_results_per_connector=10,
            registry=registry,
            allow_approval_required=False,
        )
        error: str | None = None
    except ResearchEngineError as exc:
        sources = []
        error = str(exc)[:300]

    context, refs = _source_context(sources, max_chars=max_context_chars)
    metadata = {
        "mode": "collected" if sources else "empty",
        "session_id": str(research_session.id),
        "connector_count": len(safe_connectors),
        "approval_blocked_connectors": blocked,
        "source_count": len(sources),
        "refs": refs,
        "error": error,
    }
    task.input_data = {**(task.input_data or {}), "research_evidence": metadata}
    session.add(
        TaskEvent(
            organization_id=task.organization_id,
            task_id=task.id,
            actor_user_id=actor_user_id,
            actor_agent_id=agent.id,
            event_type="agent.research.evidence_collected",
            details=metadata,
        )
    )
    record_audit(
        session,
        organization_id=task.organization_id,
        actor_user_id=actor_user_id,
        action="agent.research.completed",
        resource_type="task",
        resource_id=str(task.id),
        details=metadata,
    )
    session.commit()
    return ResearchEvidenceBundle(context=context, refs=refs, metadata=metadata)
