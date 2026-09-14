from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.memory import MemoryItem
from backend.app.models.orchestration import OrchestrationRun, OrchestrationStep
from backend.app.services.audit import record_audit

OUTCOME_KIND = "orchestration_outcome"
TERMINAL_STATUSES = {"succeeded", "partial", "failed", "cancelled"}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
}


def _terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _capabilities(session: Session, run: OrchestrationRun) -> set[str]:
    steps = session.scalars(
        select(OrchestrationStep).where(OrchestrationStep.orchestration_run_id == run.id)
    )
    return {
        capability
        for step in steps
        for capability in (step.required_capabilities or [])
        if capability
    }


def _overlap(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def recall_outcome_signal(
    session: Session,
    *,
    run: OrchestrationRun,
    history_limit: int = 50,
    match_limit: int = 5,
) -> dict[str, Any]:
    current_caps = _capabilities(session, run)
    current_terms = _terms(run.objective)
    memories = list(
        session.scalars(
            select(MemoryItem)
            .where(
                MemoryItem.organization_id == run.organization_id,
                MemoryItem.scope == "organization",
                MemoryItem.kind == OUTCOME_KIND,
                MemoryItem.key != f"orchestration:{run.id}",
            )
            .order_by(MemoryItem.created_at.desc())
            .limit(history_limit)
        )
    )

    matches: list[tuple[float, MemoryItem]] = []
    for item in memories:
        metadata = item.metadata_json or {}
        remembered_caps = set(metadata.get("capabilities") or [])
        remembered_terms = set(metadata.get("objective_terms") or [])
        capability_similarity = _overlap(current_caps, remembered_caps)
        objective_similarity = _overlap(current_terms, remembered_terms)
        similarity = (0.7 * capability_similarity) + (0.3 * objective_similarity)
        if similarity >= 0.2:
            matches.append((similarity, item))

    matches.sort(key=lambda pair: pair[0], reverse=True)
    matches = matches[:match_limit]
    if not matches:
        return {
            "sample_count": 0,
            "success_rate": None,
            "score_adjustment": 0,
            "reason": "no_similar_history",
            "matches": [],
        }

    total_weight = sum(similarity for similarity, _ in matches)
    successful_weight = sum(
        similarity
        for similarity, item in matches
        if bool((item.metadata_json or {}).get("successful"))
    )
    success_rate = successful_weight / total_weight if total_weight else 0.5

    sample_factor = min(1.0, len(matches) / 3)
    raw_adjustment = (success_rate - 0.5) * 20 * sample_factor
    score_adjustment = max(-10, min(10, round(raw_adjustment)))
    if success_rate >= 0.7:
        reason = "similar_history_positive"
    elif success_rate <= 0.3:
        reason = "similar_history_negative"
    else:
        reason = "similar_history_mixed"

    return {
        "sample_count": len(matches),
        "success_rate": round(success_rate, 3),
        "score_adjustment": score_adjustment,
        "reason": reason,
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


def record_orchestration_outcome(
    session: Session,
    *,
    run: OrchestrationRun,
    actor_user_id: UUID | None,
) -> MemoryItem | None:
    if run.status not in TERMINAL_STATUSES:
        return None

    key = f"orchestration:{run.id}"
    item = session.scalar(
        select(MemoryItem).where(
            MemoryItem.organization_id == run.organization_id,
            MemoryItem.kind == OUTCOME_KIND,
            MemoryItem.key == key,
        )
    )
    capabilities = sorted(_capabilities(session, run))
    sense = (run.summary or {}).get("sense") or {}
    metadata = {
        "run_id": str(run.id),
        "status": run.status,
        "successful": run.status == "succeeded",
        "objective_terms": sorted(_terms(run.objective)),
        "capabilities": capabilities,
        "sense_decision": sense.get("decision"),
        "sense_score": sense.get("score"),
        "planner_mode": ((run.context or {}).get("planner") or {}).get("mode"),
    }
    importance = 85 if run.status in {"failed", "cancelled"} else 70

    if item is None:
        item = MemoryItem(
            organization_id=run.organization_id,
            created_by_user_id=actor_user_id,
            scope="organization",
            kind=OUTCOME_KIND,
            key=key,
            content=f"{run.status.upper()}: {run.objective}",
            importance=importance,
            metadata_json=metadata,
        )
        session.add(item)
    else:
        item.content = f"{run.status.upper()}: {run.objective}"
        item.importance = importance
        item.metadata_json = metadata

    session.flush()
    record_audit(
        session,
        organization_id=run.organization_id,
        actor_user_id=actor_user_id,
        action="memory.outcome.recorded",
        resource_type="memory",
        resource_id=str(item.id),
        details={"run_id": str(run.id), "status": run.status},
    )
    session.commit()
    session.refresh(item)
    return item
