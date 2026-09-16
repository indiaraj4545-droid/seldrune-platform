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


def _priority_key(run: OrchestrationRun) -> str | None:
    value = _priority(run).get("key")
    return value if isinstance(value, str) and value else None


def _family_from_key(key: str) -> str:
    return key.split(":", 1)[0]


def _family(priority: dict[str, Any]) -> str:
    key = str(priority.get("key") or "")
    return _family_from_key(key) if key else str(priority.get("source") or "unknown")


def _terminal_attempts(attempts: list[OrchestrationRun]) -> list[OrchestrationRun]:
    return [run for run in attempts if run.status in _TERMINAL_STATUSES]


def _example(run: OrchestrationRun, *, association: str) -> dict[str, Any]:
    priority = _priority(run)
    return {
        "priority_key": priority.get("key"),
        "priority_title": priority.get("title"),
        "source": priority.get("source"),
        "command_id": str(run.id),
        "command_status": run.status,
        "objective": run.objective,
        "association": association,
        "updated_at": run.updated_at,
    }


def _confidence(resolution_count: int, unsuccessful_count: int) -> str:
    if resolution_count >= 2:
        return "high"
    if resolution_count == 1:
        return "medium"
    if unsuccessful_count:
        return "low"
    return "none"


def build_executive_outcome_memory(
    session: Session,
    organization_id: UUID,
    priorities: list[dict[str, Any]],
) -> dict[str, Any]:
    runs = list(
        session.scalars(
            select(OrchestrationRun)
            .where(OrchestrationRun.organization_id == organization_id)
            .order_by(OrchestrationRun.created_at.desc())
        )
    )
    grouped: dict[str, list[OrchestrationRun]] = defaultdict(list)
    for run in runs:
        if key := _priority_key(run):
            grouped[key].append(run)

    current_keys = {str(item.get("key")) for item in priorities if item.get("key")}
    family_resolutions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    family_unsuccessful: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for key, attempts in grouped.items():
        terminal = _terminal_attempts(attempts)
        if not terminal:
            continue
        family = _family_from_key(key)
        latest_terminal = terminal[0]
        if key not in current_keys and latest_terminal.status == "succeeded":
            family_resolutions[family].append(
                _example(latest_terminal, association="resolution_associated")
            )
        for run in terminal:
            if run.status in _UNSUCCESSFUL_STATUSES:
                family_unsuccessful[family].append(
                    _example(run, association="unsuccessful_attempt")
                )

    enriched: list[dict[str, Any]] = []
    for priority in priorities:
        family = _family(priority)
        resolutions = family_resolutions.get(family, [])
        unsuccessful = family_unsuccessful.get(family, [])
        preferred = resolutions[0] if resolutions else None
        memory = {
            "family": family,
            "confidence": _confidence(len(resolutions), len(unsuccessful)),
            "resolution_patterns": len(resolutions),
            "unsuccessful_patterns": len(unsuccessful),
            "preferred_pattern": preferred,
            "avoid_patterns": unsuccessful[:3],
            "causal_claim": False,
            "interpretation": (
                "Historical patterns are associations with recorded outcomes, not proof that the "
                "command caused the outcome."
            ),
        }
        enriched.append({**priority, "outcome_memory": memory})

    playbooks: list[dict[str, Any]] = []
    for family, resolutions in family_resolutions.items():
        if not resolutions:
            continue
        playbooks.append(
            {
                "family": family,
                "resolution_patterns": len(resolutions),
                "confidence": _confidence(
                    len(resolutions), len(family_unsuccessful.get(family, []))
                ),
                "latest": resolutions[0],
            }
        )
    playbooks.sort(
        key=lambda item: item["latest"]["updated_at"],
        reverse=True,
    )

    return {
        "priorities": enriched,
        "summary": {
            "learned_families": len(family_resolutions),
            "resolution_patterns": sum(len(items) for items in family_resolutions.values()),
            "unsuccessful_patterns": sum(
                len(items) for items in family_unsuccessful.values()
            ),
        },
        "playbooks": playbooks[:8],
    }
