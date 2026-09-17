from datetime import datetime
from typing import Any

from backend.app.models.orchestration import OrchestrationRun
from backend.app.models.security_event import SecurityEvent


def _approval_status(command: OrchestrationRun) -> str:
    owner_command = (command.context or {}).get("owner_command") or {}
    return str(owner_command.get("approval_status") or "awaiting_approval")


def _sort_timestamp(value: Any) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _attention_item(
    *,
    kind: str,
    category: str,
    severity: str,
    attention_rank: int,
    title: str,
    detail: str,
    resource_type: str,
    resource_id: str | None,
    occurred_at: Any,
    action: dict[str, Any],
    meta: str = "",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "category": category,
        "severity": severity,
        "attention_rank": attention_rank,
        "title": title,
        "detail": detail,
        "meta": meta,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "occurred_at": occurred_at,
        "action": action,
    }


def _security_title(event: SecurityEvent) -> str:
    if event.event_type == "refresh_token_reuse":
        return "Refresh token reuse detected"
    if event.event_type == "webhook_authentication_rejected":
        return "Webhook authentication rejected"
    return "Security event requires attention"


def build_owner_attention(
    *,
    dashboard: dict[str, Any],
    executive_brief: dict[str, Any],
    commands: list[OrchestrationRun],
    security_events: list[SecurityEvent] | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []

    for event in security_events or []:
        if event.status != "open" or event.severity not in {"critical", "warning"}:
            continue
        critical = event.severity == "critical"
        items.append(
            _attention_item(
                kind="critical_security_event" if critical else "warning_security_event",
                category="security",
                severity=event.severity,
                attention_rank=500 if critical else 200,
                title=_security_title(event),
                detail="Review and acknowledge this security event in the security center.",
                resource_type="security_event",
                resource_id=str(event.id),
                occurred_at=event.occurred_at,
                action={
                    "kind": "navigate",
                    "label": "Open security center",
                    "href": (
                        f"/api/v1/organizations/{event.organization_id}/security-events"
                        "?status=open"
                    ),
                },
            )
        )

    incidents = (dashboard.get("operational_incidents") or {}).get("recent") or []
    for incident in incidents:
        severity = str(incident.get("severity") or "warning")
        if severity not in {"critical", "warning"}:
            continue
        critical = severity == "critical"
        items.append(
            _attention_item(
                kind="critical_incident" if critical else "warning_incident",
                category="incident",
                severity=severity,
                attention_rank=400 if critical else 100,
                title=str(incident.get("title") or "Operational incident"),
                detail=str(incident.get("detail") or incident.get("type") or "Incident"),
                resource_type=str(incident.get("type") or "incident"),
                resource_id=(
                    str(incident.get("resource_id")) if incident.get("resource_id") else None
                ),
                occurred_at=incident.get("occurred_at"),
                action={
                    "kind": "navigate",
                    "label": "Open incidents",
                    "href": "#incident-title",
                },
            )
        )

    for priority in executive_brief.get("priorities") or []:
        review = priority.get("strategy_review") or {}
        if not review.get("required") or review.get("current"):
            continue
        stale = review.get("status") == "stale"
        detail = (
            "Previously reviewed strategy evidence changed. A current owner review is required "
            "before a new governed command can be created."
            if stale
            else "A comparative strategy recommendation requires owner review before command "
            "creation."
        )
        items.append(
            _attention_item(
                kind="stale_strategy_review" if stale else "pending_strategy_review",
                category="strategy_review",
                severity="review",
                attention_rank=350 if stale else 325,
                title=str(priority.get("title") or "Strategy review required"),
                detail=detail,
                resource_type="executive_priority",
                resource_id=str(priority.get("key")) if priority.get("key") else None,
                occurred_at=review.get("reviewed_at"),
                meta=str(priority.get("detail") or ""),
                action={
                    "kind": "navigate",
                    "label": "Open Review Drift",
                    "href": "/console-assets/executive-brief.html",
                },
            )
        )

    for command in commands:
        if _approval_status(command) != "awaiting_approval":
            continue
        items.append(
            _attention_item(
                kind="command_approval",
                category="command_approval",
                severity="approval",
                attention_rank=250,
                title=command.objective,
                detail=(
                    "Governed plan is waiting for the owner to inspect its decision brief and "
                    "explicitly approve or reject execution."
                ),
                resource_type="owner_command",
                resource_id=str(command.id),
                occurred_at=command.created_at,
                action={
                    "kind": "review_command",
                    "label": "Review command",
                    "command_id": str(command.id),
                },
            )
        )

    items.sort(
        key=lambda item: (
            int(item["attention_rank"]),
            _sort_timestamp(item.get("occurred_at")),
        ),
        reverse=True,
    )

    summary = {
        "total": len(items),
        "critical": sum(
            item["kind"] in {"critical_incident", "critical_security_event"} for item in items
        ),
        "reviews": sum(item["category"] == "strategy_review" for item in items),
        "approvals": sum(item["kind"] == "command_approval" for item in items),
        "warnings": sum(
            item["kind"] in {"warning_incident", "warning_security_event"} for item in items
        ),
    }
    return {
        "summary": summary,
        "items": items,
        "read_only": True,
        "governance": {
            "approval_gate_bypassed": False,
            "strategy_review_gate_bypassed": False,
            "execution_triggered": False,
        },
    }
