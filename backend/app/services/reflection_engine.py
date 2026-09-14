from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.agent import Agent
from backend.app.models.memory import MemoryItem
from backend.app.models.orchestration import OrchestrationRun, OrchestrationStep
from backend.app.models.task import Task
from backend.app.services.audit import record_audit

REFLECTION_KIND = "orchestration_reflection"
REFLECTION_VERSION = "reflection-v1"
TERMINAL_STATUSES = {"succeeded", "partial", "failed", "cancelled"}
_STOPWORDS = {"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"}


def _terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _overlap(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _run_steps(session: Session, run: OrchestrationRun) -> list[OrchestrationStep]:
    return list(
        session.scalars(
            select(OrchestrationStep)
            .where(OrchestrationStep.orchestration_run_id == run.id)
            .order_by(OrchestrationStep.sequence)
        )
    )


def build_execution_reflection(session: Session, *, run: OrchestrationRun) -> dict[str, Any]:
    steps = _run_steps(session, run)
    execution = (run.summary or {}).get("autonomous_execution") or {}
    research = (run.summary or {}).get("research_preflight") or {}
    planner = (run.context or {}).get("planner") or {}

    capability_performance: dict[str, dict[str, Any]] = {}
    agent_performance: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    match_scores: list[int] = []

    for step in steps:
        task = session.get(Task, step.task_id)
        status = task.status if task is not None else "missing"
        if step.assigned_agent_id is not None:
            match_scores.append(int(step.match_score or 0))

        for capability in step.required_capabilities or []:
            stats = capability_performance.setdefault(
                capability,
                {"succeeded": 0, "failed": 0, "blocked": 0, "match_scores": []},
            )
            if status == "succeeded":
                stats["succeeded"] += 1
            elif status in {"failed", "cancelled"}:
                stats["failed"] += 1
            else:
                stats["blocked"] += 1
            if step.assigned_agent_id is not None:
                stats["match_scores"].append(int(step.match_score or 0))

        if task is not None and task.error_message:
            error = task.error_message.strip()[:300]
            if error and error not in errors:
                errors.append(error)

        if step.assigned_agent_id is not None:
            agent = session.get(Agent, step.assigned_agent_id)
            key = str(step.assigned_agent_id)
            stats = agent_performance.setdefault(
                key,
                {
                    "name": agent.name if agent is not None else key,
                    "succeeded": 0,
                    "failed": 0,
                    "blocked": 0,
                    "match_scores": [],
                },
            )
            if status == "succeeded":
                stats["succeeded"] += 1
            elif status in {"failed", "cancelled"}:
                stats["failed"] += 1
            else:
                stats["blocked"] += 1
            stats["match_scores"].append(int(step.match_score or 0))

    for collection in (capability_performance, agent_performance):
        for stats in collection.values():
            scores = stats.pop("match_scores")
            stats["average_match"] = round(sum(scores) / len(scores)) if scores else 0
            stats["attempted"] = stats["succeeded"] + stats["failed"] + stats["blocked"]

    average_match = round(sum(match_scores) / len(match_scores)) if match_scores else 0
    strengths: list[str] = []
    cautions: list[str] = []
    recommendations: list[str] = []

    if run.status == "succeeded":
        strengths.append("orchestration_completed_successfully")
    elif run.status in {"failed", "partial"}:
        cautions.append("orchestration_did_not_complete_cleanly")

    if average_match >= 90 and run.status == "succeeded":
        strengths.append("high_fit_agent_routing_succeeded")
        recommendations.append("prefer_high_fit_agent_routes_for_similar_capabilities")
    elif average_match and average_match < 70:
        cautions.append("low_agent_fit_was_present")
        recommendations.append("raise_routing_quality_before_similar_execution")

    retries = int(execution.get("retried_steps") or 0)
    if retries:
        cautions.append("execution_required_retries")
        recommendations.append("retain_a_bounded_retry_budget_for_similar_work")

    failed_steps = int(execution.get("failed_steps") or 0)
    blocked_steps = int(execution.get("blocked_steps") or 0)
    if failed_steps:
        cautions.append("task_failures_were_observed")
        recommendations.append("review_failed_capabilities_before_repeating_similar_work")
    if blocked_steps:
        cautions.append("execution_encountered_blocked_steps")
        recommendations.append("resolve_assignment_or_dependency_blockers_before_retry")

    source_count = int(research.get("source_count") or 0)
    if source_count > 0 and run.status == "succeeded":
        strengths.append("research_evidence_preceded_success")
        recommendations.append("preserve_research_preflight_for_similar_work")

    planner_mode = str(planner.get("mode") or "unknown")
    if planner_mode == "fallback" and run.status in {"failed", "partial"}:
        cautions.append("fallback_planning_preceded_a_weak_outcome")
        recommendations.append("prefer_live_planning_for_similar_work_when_available")

    if errors:
        cautions.append("runtime_errors_were_recorded")

    if not recommendations:
        recommendation = (
            "reuse_the_current_execution_pattern"
            if run.status == "succeeded"
            else "require_review_before_retry"
        )
        recommendations.append(recommendation)

    return {
        "version": REFLECTION_VERSION,
        "run_id": str(run.id),
        "status": run.status,
        "strengths": strengths,
        "cautions": cautions,
        "recommendations": recommendations,
        "capability_performance": capability_performance,
        "agent_performance": agent_performance,
        "errors": errors[:5],
        "signals": {
            "planner_mode": planner_mode,
            "average_agent_match": average_match,
            "research_source_count": source_count,
            "retried_steps": retries,
            "failed_steps": failed_steps,
            "blocked_steps": blocked_steps,
        },
    }


def record_execution_reflection(
    session: Session,
    *,
    run: OrchestrationRun,
    actor_user_id: UUID | None,
) -> MemoryItem | None:
    if run.status not in TERMINAL_STATUSES:
        return None

    reflection = build_execution_reflection(session, run=run)
    key = f"reflection:{run.id}"
    item = session.scalar(
        select(MemoryItem).where(
            MemoryItem.organization_id == run.organization_id,
            MemoryItem.kind == REFLECTION_KIND,
            MemoryItem.key == key,
        )
    )
    capabilities = sorted(reflection["capability_performance"].keys())
    metadata = {
        "run_id": str(run.id),
        "status": run.status,
        "objective_terms": sorted(_terms(run.objective)),
        "capabilities": capabilities,
        "reflection": reflection,
    }
    content = "; ".join(reflection["recommendations"])[:2000]
    importance = 90 if reflection["cautions"] else 75

    if item is None:
        item = MemoryItem(
            organization_id=run.organization_id,
            created_by_user_id=actor_user_id,
            scope="organization",
            kind=REFLECTION_KIND,
            key=key,
            content=content,
            importance=importance,
            metadata_json=metadata,
        )
        session.add(item)
    else:
        item.content = content
        item.importance = importance
        item.metadata_json = metadata

    run.summary = {**(run.summary or {}), "reflection": reflection}
    session.flush()
    record_audit(
        session,
        organization_id=run.organization_id,
        actor_user_id=actor_user_id,
        action="memory.reflection.recorded",
        resource_type="memory",
        resource_id=str(item.id),
        details={
            "run_id": str(run.id),
            "status": run.status,
            "recommendation_count": len(reflection["recommendations"]),
        },
    )
    session.commit()
    session.refresh(item)
    session.refresh(run)
    return item


def recall_reflection_signal(
    session: Session,
    *,
    run: OrchestrationRun,
    history_limit: int = 50,
    match_limit: int = 5,
) -> dict[str, Any]:
    current_caps = {
        capability
        for step in _run_steps(session, run)
        for capability in (step.required_capabilities or [])
    }
    current_terms = _terms(run.objective)
    memories = list(
        session.scalars(
            select(MemoryItem)
            .where(
                MemoryItem.organization_id == run.organization_id,
                MemoryItem.scope == "organization",
                MemoryItem.kind == REFLECTION_KIND,
                MemoryItem.key != f"reflection:{run.id}",
            )
            .order_by(MemoryItem.created_at.desc())
            .limit(history_limit)
        )
    )

    matches: list[tuple[float, MemoryItem]] = []
    for item in memories:
        metadata = item.metadata_json or {}
        capability_similarity = _overlap(current_caps, set(metadata.get("capabilities") or []))
        objective_similarity = _overlap(current_terms, set(metadata.get("objective_terms") or []))
        similarity = (0.75 * capability_similarity) + (0.25 * objective_similarity)
        if similarity >= 0.2:
            matches.append((similarity, item))

    matches.sort(key=lambda pair: pair[0], reverse=True)
    matches = matches[:match_limit]
    if not matches:
        return {
            "sample_count": 0,
            "capability_success_rate": None,
            "score_adjustment": 0,
            "reason": "no_reflection_history",
            "review_recommended": False,
            "recurring_cautions": [],
            "lessons": [],
            "matches": [],
        }

    success_weight = 0.0
    evidence_weight = 0.0
    caution_counts: dict[str, int] = {}
    lessons: list[str] = []

    for similarity, item in matches:
        reflection = ((item.metadata_json or {}).get("reflection") or {})
        capability_stats = reflection.get("capability_performance") or {}
        for capability in current_caps:
            stats = capability_stats.get(capability)
            if not isinstance(stats, dict):
                continue
            succeeded = int(stats.get("succeeded") or 0)
            failed = int(stats.get("failed") or 0)
            blocked = int(stats.get("blocked") or 0)
            attempted = succeeded + failed + blocked
            if attempted:
                evidence_weight += similarity * attempted
                success_weight += similarity * succeeded

        for caution in reflection.get("cautions") or []:
            caution_counts[str(caution)] = caution_counts.get(str(caution), 0) + 1
        for recommendation in reflection.get("recommendations") or []:
            recommendation = str(recommendation)
            if recommendation not in lessons:
                lessons.append(recommendation)

    if evidence_weight:
        success_rate = success_weight / evidence_weight
        sample_factor = min(1.0, len(matches) / 3)
        score_adjustment = max(-6, min(6, round((success_rate - 0.5) * 12 * sample_factor)))
    else:
        success_rate = None
        score_adjustment = 0

    recurring_cautions = sorted(
        caution for caution, count in caution_counts.items() if count >= 2
    )[:5]
    if isinstance(success_rate, float) and success_rate >= 0.7:
        reason = "reflection_lessons_positive"
    elif isinstance(success_rate, float) and success_rate <= 0.4:
        reason = "reflection_lessons_negative"
    else:
        reason = "reflection_lessons_mixed"

    review_recommended = bool(
        len(matches) >= 2
        and (
            (isinstance(success_rate, float) and success_rate <= 0.4)
            or "low_agent_fit_was_present" in recurring_cautions
            or "task_failures_were_observed" in recurring_cautions
        )
    )
    capability_success_rate = (
        round(success_rate, 3) if isinstance(success_rate, float) else None
    )

    return {
        "sample_count": len(matches),
        "capability_success_rate": capability_success_rate,
        "score_adjustment": score_adjustment,
        "reason": reason,
        "review_recommended": review_recommended,
        "recurring_cautions": recurring_cautions,
        "lessons": lessons[:5],
        "matches": [
            {
                "memory_id": str(item.id),
                "run_id": (item.metadata_json or {}).get("run_id"),
                "status": (item.metadata_json or {}).get("status"),
                "similarity": round(similarity, 3),
            }
            for similarity, item in matches
        ],
    }
