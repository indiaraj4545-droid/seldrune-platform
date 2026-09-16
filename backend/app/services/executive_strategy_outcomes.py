from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.orchestration import OrchestrationRun

_TERMINAL_STATUSES = {"succeeded", "partial", "failed", "cancelled"}
_UNSUCCESSFUL_STATUSES = {"partial", "failed", "cancelled"}


def _priority(run: OrchestrationRun) -> dict[str, Any]:
    value = (run.context or {}).get("executive_priority") or {}
    return value if isinstance(value, dict) else {}


def _strategy(run: OrchestrationRun) -> dict[str, Any]:
    value = (run.context or {}).get("executive_strategy") or {}
    return value if isinstance(value, dict) else {}


def _family_from_key(key: str) -> str:
    return key.split(":", 1)[0]


def _family(priority: dict[str, Any]) -> str:
    key = str(priority.get("key") or "")
    return _family_from_key(key) if key else str(priority.get("source") or "unknown")


def _evidence_strength(attempts: int, resolutions: int) -> str:
    if resolutions >= 2 and attempts >= 3:
        return "high"
    if resolutions >= 1 and attempts >= 2:
        return "medium"
    if attempts >= 1:
        return "low"
    return "none"


def _empty_scorecard(family: str, mode: str) -> dict[str, Any]:
    return {
        "family": family,
        "mode": mode,
        "attempts": 0,
        "execution_succeeded": 0,
        "resolution_associations": 0,
        "persisted_after_success": 0,
        "unsuccessful_attempts": 0,
        "resolution_rate": 0.0,
        "evidence_strength": "none",
        "causal_claim": False,
    }


def build_executive_strategy_outcomes(
    session: Session,
    organization_id: UUID,
    priorities: list[dict[str, Any]],
) -> dict[str, Any]:
    current_keys = {str(item.get("key")) for item in priorities if item.get("key")}
    scorecards: dict[tuple[str, str], dict[str, Any]] = {}
    recent: list[dict[str, Any]] = []

    runs = list(
        session.scalars(
            select(OrchestrationRun)
            .where(OrchestrationRun.organization_id == organization_id)
            .order_by(OrchestrationRun.updated_at.desc())
        )
    )
    for run in runs:
        priority = _priority(run)
        strategy = _strategy(run)
        key = priority.get("key")
        mode = strategy.get("mode")
        if not key or not mode or run.status not in _TERMINAL_STATUSES:
            continue

        family = _family_from_key(str(key))
        card_key = (family, str(mode))
        card = scorecards.setdefault(card_key, _empty_scorecard(*card_key))
        card["attempts"] += 1

        resolved = run.status == "succeeded" and str(key) not in current_keys
        persisted = run.status == "succeeded" and str(key) in current_keys
        unsuccessful = run.status in _UNSUCCESSFUL_STATUSES
        if run.status == "succeeded":
            card["execution_succeeded"] += 1
        if resolved:
            card["resolution_associations"] += 1
        if persisted:
            card["persisted_after_success"] += 1
        if unsuccessful:
            card["unsuccessful_attempts"] += 1

        recent.append(
            {
                "command_id": str(run.id),
                "priority_key": str(key),
                "family": family,
                "mode": str(mode),
                "command_status": run.status,
                "outcome": (
                    "resolution_associated"
                    if resolved
                    else "persisted_after_success"
                    if persisted
                    else "unsuccessful_attempt"
                ),
                "updated_at": run.updated_at,
                "causal_claim": False,
            }
        )

    for card in scorecards.values():
        attempts = int(card["attempts"])
        resolutions = int(card["resolution_associations"])
        card["resolution_rate"] = round(resolutions / attempts, 4) if attempts else 0.0
        card["evidence_strength"] = _evidence_strength(attempts, resolutions)

    by_family: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for (family, mode), card in scorecards.items():
        by_family[family][mode] = card

    enriched: list[dict[str, Any]] = []
    for priority in priorities:
        family = _family(priority)
        modes = by_family.get(family, {})
        enriched.append(
            {
                **priority,
                "strategy_outcomes": {
                    "family": family,
                    "total_attempts": sum(int(item["attempts"]) for item in modes.values()),
                    "resolution_associations": sum(
                        int(item["resolution_associations"]) for item in modes.values()
                    ),
                    "modes": modes,
                    "causal_claim": False,
                    "interpretation": (
                        "Strategy scorecards describe recorded associations between governed "
                        "commands and later priority state; they do not prove causation."
                    ),
                },
            }
        )

    ordered_scorecards = sorted(
        scorecards.values(),
        key=lambda item: (
            -int(item["resolution_associations"]),
            -float(item["resolution_rate"]),
            -int(item["attempts"]),
            str(item["family"]),
            str(item["mode"]),
        ),
    )
    return {
        "priorities": enriched,
        "summary": {
            "scored_attempts": sum(int(item["attempts"]) for item in scorecards.values()),
            "verified_resolution_associations": sum(
                int(item["resolution_associations"]) for item in scorecards.values()
            ),
            "persisted_after_success": sum(
                int(item["persisted_after_success"]) for item in scorecards.values()
            ),
            "unsuccessful_attempts": sum(
                int(item["unsuccessful_attempts"]) for item in scorecards.values()
            ),
            "scored_families": len(by_family),
        },
        "scorecards": ordered_scorecards[:12],
        "recent": recent[:12],
    }
