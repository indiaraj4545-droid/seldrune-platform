from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.memory import MemoryItem
from backend.app.services.outcome_memory import OUTCOME_KIND
from backend.app.services.reflection_engine import REFLECTION_KIND

ADAPTIVE_PLANNING_VERSION = "adaptive-planning-v1"
_STOPWORDS = {"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"}
_RECOMMENDATION_ADVISORIES = {
    "prefer_high_fit_agent_routes_for_similar_capabilities": (
        "Keep steps narrow and capability-specific so downstream routing can select a high-fit agent."
    ),
    "raise_routing_quality_before_similar_execution": (
        "Avoid broad multi-purpose steps; separate work so each step has one primary capability."
    ),
    "retain_a_bounded_retry_budget_for_similar_work": (
        "Design steps to be independently retryable and keep dependencies explicit."
    ),
    "review_failed_capabilities_before_repeating_similar_work": (
        "Include an explicit validation checkpoint for capabilities that failed in similar work."
    ),
    "resolve_assignment_or_dependency_blockers_before_retry": (
        "Surface dependencies and readiness checks before execution steps that previously blocked."
    ),
    "preserve_research_preflight_for_similar_work": (
        "Preserve a research or evidence-gathering step when it is relevant to the objective."
    ),
    "prefer_live_planning_for_similar_work_when_available": (
        "Make assumptions and evidence requirements explicit because prior fallback planning underperformed."
    ),
    "reuse_the_current_execution_pattern": (
        "Reuse the successful high-level execution pattern where it still fits the owner's objective."
    ),
    "require_review_before_retry": (
        "Include a validation or review checkpoint before repeating a previously weak execution pattern."
    ),
}
_CAUTION_ADVISORIES = {
    "low_agent_fit_was_present": (
        "Keep each step focused on one primary capability to improve downstream agent fit."
    ),
    "task_failures_were_observed": (
        "Add a validation checkpoint after historically failure-prone work when plan shape permits."
    ),
    "execution_encountered_blocked_steps": (
        "Expose dependencies or readiness checks before historically blocked work."
    ),
    "fallback_planning_preceded_a_weak_outcome": (
        "State assumptions and acceptance criteria explicitly in the plan."
    ),
    "runtime_errors_were_recorded": (
        "Keep risky steps isolated so failures do not cascade across the whole plan."
    ),
}


def _terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _overlap(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _empty_guidance() -> dict[str, Any]:
    return {
        "version": ADAPTIVE_PLANNING_VERSION,
        "applied": False,
        "sample_count": 0,
        "reflection_sample_count": 0,
        "outcome_sample_count": 0,
        "historical_success_rate": None,
        "confidence": 0.0,
        "preferred_capabilities": [],
        "caution_capabilities": [],
        "recommendations": [],
        "recurring_cautions": [],
        "advisories": [],
    }


def _rank_matches(
    items: list[MemoryItem],
    *,
    objective_terms: set[str],
    match_limit: int,
) -> list[tuple[float, MemoryItem]]:
    matches: list[tuple[float, MemoryItem]] = []
    for item in items:
        remembered_terms = set((item.metadata_json or {}).get("objective_terms") or [])
        similarity = _overlap(objective_terms, remembered_terms)
        if similarity >= 0.15:
            matches.append((similarity, item))
    matches.sort(key=lambda pair: pair[0], reverse=True)
    return matches[:match_limit]


def build_adaptive_planning_guidance(
    session: Session,
    *,
    organization_id: UUID,
    objective: str,
    history_limit: int = 80,
    match_limit: int = 5,
) -> dict[str, Any]:
    objective_terms = _terms(objective)
    if not objective_terms:
        return _empty_guidance()

    items = list(
        session.scalars(
            select(MemoryItem)
            .where(
                MemoryItem.organization_id == organization_id,
                MemoryItem.scope == "organization",
                MemoryItem.kind.in_([OUTCOME_KIND, REFLECTION_KIND]),
            )
            .order_by(MemoryItem.created_at.desc())
            .limit(history_limit)
        )
    )
    reflections = [item for item in items if item.kind == REFLECTION_KIND]
    outcomes = [item for item in items if item.kind == OUTCOME_KIND]
    reflection_matches = _rank_matches(
        reflections,
        objective_terms=objective_terms,
        match_limit=match_limit,
    )
    outcome_matches = _rank_matches(
        outcomes,
        objective_terms=objective_terms,
        match_limit=match_limit,
    )
    sample_count = max(len(reflection_matches), len(outcome_matches))
    if sample_count == 0:
        return _empty_guidance()

    recommendation_scores: dict[str, float] = {}
    caution_counts: dict[str, int] = {}
    capability_stats: dict[str, dict[str, float]] = {}

    for similarity, item in reflection_matches:
        reflection = ((item.metadata_json or {}).get("reflection") or {})
        for recommendation in reflection.get("recommendations") or []:
            key = str(recommendation)
            recommendation_scores[key] = recommendation_scores.get(key, 0.0) + similarity
        for caution in reflection.get("cautions") or []:
            key = str(caution)
            caution_counts[key] = caution_counts.get(key, 0) + 1
        for capability, stats in (reflection.get("capability_performance") or {}).items():
            if not isinstance(stats, dict):
                continue
            succeeded = int(stats.get("succeeded") or 0)
            failed = int(stats.get("failed") or 0)
            blocked = int(stats.get("blocked") or 0)
            attempted = succeeded + failed + blocked
            if attempted == 0:
                continue
            aggregate = capability_stats.setdefault(
                str(capability),
                {"successful": 0.0, "attempted": 0.0},
            )
            aggregate["successful"] += similarity * succeeded
            aggregate["attempted"] += similarity * attempted

    weighted_outcomes = [
        (similarity, bool((item.metadata_json or {}).get("successful")))
        for similarity, item in outcome_matches
    ]
    if weighted_outcomes:
        total_weight = sum(similarity for similarity, _ in weighted_outcomes)
        success_weight = sum(
            similarity for similarity, successful in weighted_outcomes if successful
        )
        historical_success_rate = success_weight / total_weight if total_weight else None
    else:
        historical_success_rate = None

    capability_rates: list[tuple[str, float, float]] = []
    for capability, stats in capability_stats.items():
        attempted = stats["attempted"]
        if attempted:
            capability_rates.append(
                (capability, stats["successful"] / attempted, attempted)
            )
    capability_rates.sort(key=lambda item: (item[1], item[2]), reverse=True)
    preferred_capabilities = [
        capability for capability, success_rate, _ in capability_rates if success_rate >= 0.7
    ][:5]
    caution_capabilities = [
        capability for capability, success_rate, _ in capability_rates if success_rate <= 0.4
    ][:5]

    recommendations = [
        recommendation
        for recommendation, _ in sorted(
            recommendation_scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:5]
    ]
    recurring_cautions = sorted(
        (caution for caution, count in caution_counts.items() if count >= 2),
        key=lambda caution: caution_counts[caution],
        reverse=True,
    )[:5]

    advisories: list[str] = []
    for recommendation in recommendations:
        advisory = _RECOMMENDATION_ADVISORIES.get(recommendation)
        if advisory and advisory not in advisories:
            advisories.append(advisory)
    for caution in recurring_cautions:
        advisory = _CAUTION_ADVISORIES.get(caution)
        if advisory and advisory not in advisories:
            advisories.append(advisory)
    for capability in caution_capabilities:
        advisory = (
            f"Historical evidence for the '{capability}' capability is weak; add validation "
            "or isolate that step when the objective requires it."
        )
        if advisory not in advisories:
            advisories.append(advisory)

    confidence = min(1.0, sample_count / 3)
    return {
        "version": ADAPTIVE_PLANNING_VERSION,
        "applied": True,
        "sample_count": sample_count,
        "reflection_sample_count": len(reflection_matches),
        "outcome_sample_count": len(outcome_matches),
        "historical_success_rate": (
            round(historical_success_rate, 3)
            if isinstance(historical_success_rate, float)
            else None
        ),
        "confidence": round(confidence, 3),
        "preferred_capabilities": preferred_capabilities,
        "caution_capabilities": caution_capabilities,
        "recommendations": recommendations,
        "recurring_cautions": recurring_cautions,
        "advisories": advisories[:6],
    }
