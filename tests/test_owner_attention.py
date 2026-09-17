from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from backend.app.services.owner_attention import build_owner_attention


def _command(*, objective: str, approval_status: str, created_at: datetime):
    return SimpleNamespace(
        id=uuid4(),
        objective=objective,
        created_at=created_at,
        context={"owner_command": {"approval_status": approval_status}},
    )


def test_owner_attention_prioritizes_governed_attention() -> None:
    now = datetime.now(UTC)
    dashboard = {
        "operational_incidents": {
            "recent": [
                {
                    "type": "task_failed",
                    "severity": "critical",
                    "title": "Critical task failure",
                    "detail": "A governed task failed",
                    "resource_id": "task-1",
                    "occurred_at": now - timedelta(minutes=5),
                },
                {
                    "type": "project_blocked",
                    "severity": "warning",
                    "title": "Blocked project",
                    "detail": "Owner review required",
                    "resource_id": "project-1",
                    "occurred_at": now,
                },
            ]
        }
    }
    executive_brief = {
        "priorities": [
            {
                "key": "stale-review",
                "title": "Re-review changed evidence",
                "detail": "Advisory evidence changed",
                "strategy_review": {
                    "required": True,
                    "current": False,
                    "status": "stale",
                    "reviewed_at": now - timedelta(hours=1),
                },
            },
            {
                "key": "pending-review",
                "title": "Review strategy",
                "detail": "Comparative evidence is available",
                "strategy_review": {
                    "required": True,
                    "current": False,
                    "status": "pending",
                    "reviewed_at": None,
                },
            },
            {
                "key": "current-review",
                "title": "Already reviewed",
                "strategy_review": {
                    "required": True,
                    "current": True,
                    "status": "current",
                },
            },
        ]
    }
    commands = [
        _command(
            objective="Approve governed launch",
            approval_status="awaiting_approval",
            created_at=now - timedelta(minutes=1),
        ),
        _command(
            objective="Already approved",
            approval_status="approved",
            created_at=now,
        ),
    ]

    result = build_owner_attention(
        dashboard=dashboard,
        executive_brief=executive_brief,
        commands=commands,
    )

    assert [item["kind"] for item in result["items"]] == [
        "critical_incident",
        "stale_strategy_review",
        "pending_strategy_review",
        "command_approval",
        "warning_incident",
    ]
    assert result["summary"] == {
        "total": 5,
        "critical": 1,
        "reviews": 2,
        "approvals": 1,
        "warnings": 1,
    }
    assert result["read_only"] is True
    assert result["governance"] == {
        "approval_gate_bypassed": False,
        "strategy_review_gate_bypassed": False,
        "execution_triggered": False,
    }


def test_owner_attention_route_is_get_only(client) -> None:
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    path = "/api/v1/organizations/{organization_id}/owner-attention"
    assert path in schema.json()["paths"]
    assert set(schema.json()["paths"][path]) == {"get"}
