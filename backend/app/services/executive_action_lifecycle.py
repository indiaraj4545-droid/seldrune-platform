from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.orchestration import OrchestrationRun


def _priority_key(run: OrchestrationRun) -> str | None:
    value = ((run.context or {}).get("executive_priority") or {}).get("key")
    return value if isinstance(value, str) and value else None


def _approval_status(run: OrchestrationRun) -> str | None:
    value = ((run.context or {}).get("owner_command") or {}).get("approval_status")
    return value if isinstance(value, str) else None


def _state(run: OrchestrationRun) -> str:
    approval = _approval_status(run)
    if run.status == "planned" and approval == "awaiting_approval":
        return "awaiting_approval"
    if run.status in {"planned", "active"}:
        return "active"
    if run.status == "succeeded":
        return "succeeded_unresolved"
    if run.status == "partial":
        return "partial"
    if run.status == "failed":
        return "failed"
    return "cancelled"


def _run_public(run: OrchestrationRun, attempts: int) -> dict[str, Any]:
    return {
        "command_id": str(run.id),
        "state": _state(run),
        "command_status": run.status,
        "approval_status": _approval_status(run),
        "attempts": attempts,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def reconcile_executive_actions(
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

    current_keys = {item["key"] for item in priorities}
    enriched: list[dict[str, Any]] = []
    state_counts: dict[str, int] = defaultdict(int)
    for priority in priorities:
        attempts = grouped.get(priority["key"], [])
        lifecycle = (
            _run_public(attempts[0], len(attempts))
            if attempts
            else {
                "command_id": None,
                "state": "unassigned",
                "command_status": None,
                "approval_status": None,
                "attempts": 0,
                "created_at": None,
                "updated_at": None,
            }
        )
        state_counts[lifecycle["state"]] += 1
        enriched.append({**priority, "lifecycle": lifecycle})

    resolved: list[dict[str, Any]] = []
    for key, attempts in grouped.items():
        if key in current_keys:
            continue
        latest = attempts[0]
        priority = (latest.context or {}).get("executive_priority") or {}
        resolved.append(
            {
                "key": key,
                "title": priority.get("title") or latest.objective,
                "source": priority.get("source"),
                "resource_id": priority.get("resource_id"),
                "severity": priority.get("severity"),
                "state": "resolved",
                "latest_command_id": str(latest.id),
                "latest_command_status": latest.status,
                "attempts": len(attempts),
                "resolved_at": latest.updated_at,
            }
        )
    resolved.sort(key=lambda item: item["resolved_at"], reverse=True)

    return {
        "priorities": enriched,
        "summary": {
            "tracked_priorities": len(grouped),
            "current_priorities": len(priorities),
            "resolved_priorities": len(resolved),
            "states": dict(state_counts),
        },
        "resolved_recent": resolved[:8],
    }
