from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.orchestration import OrchestrationRun, OrchestrationStep
from backend.app.models.task import Task
from backend.app.services.audit import record_audit


SENSE_VERSION = "sense-v1"


@dataclass(frozen=True)
class SenseAssessment:
    decision: str
    score: int
    reasons: list[str]
    blockers: list[str]
    signals: dict[str, Any]
    recommended_action: str
    version: str = SENSE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_orchestration(
    session: Session,
    *,
    run: OrchestrationRun,
    actor_user_id: UUID | None = None,
    persist: bool = False,
) -> SenseAssessment:
    steps = list(
        session.scalars(
            select(OrchestrationStep)
            .where(OrchestrationStep.orchestration_run_id == run.id)
            .order_by(OrchestrationStep.sequence)
        )
    )
    tasks = [task for step in steps if (task := session.get(Task, step.task_id)) is not None]
    planner = (run.context or {}).get("planner", {})
    research = (run.summary or {}).get("research_preflight", {})
    previous = (run.summary or {}).get("autonomous_execution", {})

    total_steps = len(steps)
    assigned_steps = sum(step.assigned_agent_id is not None for step in steps)
    assignment_ratio = assigned_steps / total_steps if total_steps else 0.0
    match_scores = [step.match_score for step in steps if step.assigned_agent_id is not None]
    average_match = round(sum(match_scores) / len(match_scores)) if match_scores else 0
    failed_tasks = sum(task.status == "failed" for task in tasks)
    planner_mode = str(planner.get("mode") or "unknown")
    source_count = int(research.get("source_count") or 0)
    blocked_connectors = int(research.get("approval_blocked_connectors") or 0)
    previous_failed = int(previous.get("failed_steps") or 0)

    score = 50
    reasons: list[str] = []
    blockers: list[str] = []

    if planner_mode == "live":
        score += 20
        reasons.append("live_planner")
    elif planner_mode == "fallback":
        score -= 10
        reasons.append("fallback_planner")

    if assignment_ratio == 1.0 and total_steps:
        score += 15
        reasons.append("all_steps_assigned")
    elif assignment_ratio < 1.0:
        score -= 30
        blockers.append("unassigned_steps")

    if average_match >= 90:
        score += 10
        reasons.append("strong_agent_fit")
    elif average_match and average_match < 70:
        score -= 10
        reasons.append("weak_agent_fit")

    if source_count > 0:
        score += 5
        reasons.append("research_evidence_available")
    if blocked_connectors > 0:
        score -= 25
        blockers.append("research_connector_requires_approval")
    if failed_tasks or previous_failed:
        score -= 15
        reasons.append("prior_execution_failure")

    score = max(0, min(100, score))
    if blockers:
        decision = "HOLD"
        recommended_action = "Resolve blockers before execution"
    elif planner_mode == "fallback" or score < 65 or failed_tasks or previous_failed:
        decision = "REVIEW"
        recommended_action = "Owner review is recommended before execution"
    else:
        decision = "GO"
        recommended_action = "Proceed with governed execution"

    assessment = SenseAssessment(
        decision=decision,
        score=score,
        reasons=reasons,
        blockers=blockers,
        signals={
            "planner_mode": planner_mode,
            "step_count": total_steps,
            "assigned_steps": assigned_steps,
            "assignment_ratio": round(assignment_ratio, 3),
            "average_agent_match": average_match,
            "research_source_count": source_count,
            "blocked_connectors": blocked_connectors,
            "failed_tasks": failed_tasks,
            "previous_failed_steps": previous_failed,
        },
        recommended_action=recommended_action,
    )

    if persist:
        run.summary = {**(run.summary or {}), "sense": assessment.to_dict()}
        record_audit(
            session,
            organization_id=run.organization_id,
            actor_user_id=actor_user_id,
            action="orchestration.sense.assessed",
            resource_type="orchestration",
            resource_id=str(run.id),
            details=assessment.to_dict(),
        )
        session.commit()
        session.refresh(run)

    return assessment
