from tests.test_autonomous_execution import register_owner

pytest_plugins = ["tests.test_autonomous_execution"]


def test_owner_dashboard_and_decision_brief(client) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands",
        headers=headers,
        json={"objective": "Analyze healthcare denial management opportunities"},
    )
    assert created.status_code == 201
    command = created.json()

    dashboard = client.get(
        f"/api/v1/organizations/{organization_id}/owner-dashboard", headers=headers
    )
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["command_counts"]["total"] == 1
    assert body["command_counts"]["awaiting_approval"] == 1
    assert body["execution"]["total_steps"] == 3
    assert body["execution"]["matched_steps"] == 3
    assert body["usage"]["total_tokens"] == 0
    assert body["operational_incidents"] == {
        "total": 0,
        "critical": 0,
        "warning": 0,
        "recent": [],
    }
    performance = body["agent_performance"]
    assert performance["agent_count"] == 5
    assert performance["active_agent_count"] == 5
    assert len(performance["ranked_agents"]) == 5
    assert all(item["success_rate"] is None for item in performance["ranked_agents"])
    assert body["treasury"] == {
        "project_count": 0,
        "metered_project_count": 0,
        "unmetered_project_count": 0,
        "allocated_budget_usd": 0,
        "spent_budget_usd": 0,
        "reserved_budget_usd": 0,
        "committed_budget_usd": 0,
        "available_budget_usd": 0,
        "utilization": 0,
        "overcommitted": False,
    }
    recent = body["recent_commands"][0]
    assert recent["forecast_cost_usd"] == 0
    assert recent["reservation"] is None
    assert recent["recorded_cost_usd"] == 0
    assert recent["budget_halted"] is False

    brief = client.get(
        f"/api/v1/organizations/{organization_id}/owner-commands/{command['id']}/brief",
        headers=headers,
    )
    assert brief.status_code == 200
    decision = brief.json()
    assert decision["approval_status"] == "awaiting_approval"
    assert decision["readiness"] == "ready"
    assert decision["risks"] == []
    assert decision["usage"]["execution_tokens"] == 0
    assert decision["usage"]["estimated_cost_usd"] == 0
    assert decision["budget_control"]["forecast_cost_usd"] == 0
    assert decision["budget_control"]["reservation"] is None
    assert decision["budget_control"]["recorded_cost_usd"] == 0
    assert decision["budget_control"]["halted"] is False
    assert all(step["output"] is None for step in decision["steps"])
    assert decision["recommended_next_action"] == "Review the plan and approve the command"


def test_owner_dashboard_aggregates_project_treasury(client) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/api/v1/organizations/{organization_id}"
    client.post(f"{base}/organization-kernel/bootstrap", headers=headers)
    department = client.get(f"{base}/departments", headers=headers).json()[0]
    project = client.post(
        f"{base}/projects",
        headers=headers,
        json={
            "name": "Treasury governed delivery",
            "slug": "treasury-governed-delivery",
            "department_id": department["id"],
            "status": "planned",
            "budget_limit_usd": 10,
            "budget_spent_usd": 2,
            "resource_limit_units": 20,
        },
    ).json()
    command = client.post(
        f"{base}/projects/{project['id']}/launch",
        headers=headers,
    ).json()
    approved = client.post(
        f"{base}/owner-commands/{command['id']}/approve",
        headers=headers,
    )
    assert approved.status_code == 200
    reserved = approved.json()["context"]["portfolio_governor"][
        "budget_reservation"
    ]["amount_usd"]

    dashboard = client.get(f"{base}/owner-dashboard", headers=headers)
    assert dashboard.status_code == 200
    treasury = dashboard.json()["treasury"]
    assert treasury["project_count"] == 1
    assert treasury["metered_project_count"] == 1
    assert treasury["allocated_budget_usd"] == 10
    assert treasury["spent_budget_usd"] == 2
    assert treasury["reserved_budget_usd"] == reserved
    assert treasury["committed_budget_usd"] == 2 + reserved
    assert treasury["available_budget_usd"] == 8 - reserved
    assert treasury["utilization"] == round((2 + reserved) / 10, 4)
    assert treasury["overcommitted"] is False


def test_agent_performance_observatory_uses_execution_evidence(client) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/api/v1/organizations/{organization_id}"
    command = client.post(
        f"{base}/owner-commands",
        headers=headers,
        json={"objective": "Research, analyze, and design a verified automation offer"},
    ).json()
    approved = client.post(
        f"{base}/owner-commands/{command['id']}/approve",
        headers=headers,
    )
    assert approved.status_code == 200
    executed = client.post(
        f"{base}/owner-commands/{command['id']}/execute",
        headers=headers,
        json={},
    )
    assert executed.status_code == 200

    dashboard = client.get(f"{base}/owner-dashboard", headers=headers)
    assert dashboard.status_code == 200
    performance = dashboard.json()["agent_performance"]
    ranked = performance["ranked_agents"]
    assert performance["agent_count"] == 5
    assert sum(item["succeeded_tasks"] for item in ranked) == len(command["steps"])
    evidenced = [item for item in ranked if item["completed_tasks"] > 0]
    assert evidenced
    assert all(item["success_rate"] == 1 for item in evidenced)
    assert all(item["failed_tasks"] == 0 for item in evidenced)
    assert all(item["total_tokens"] > 0 for item in evidenced)
    assert all(item["average_latency_ms"] is not None for item in evidenced)


def test_operational_incident_center_reports_failed_tasks(client) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/api/v1/organizations/{organization_id}"
    command = client.post(
        f"{base}/owner-commands",
        headers=headers,
        json={"objective": "Research an operational failure scenario"},
    ).json()
    task_id = command["steps"][0]["task_id"]
    running = client.post(
        f"{base}/tasks/{task_id}/transition",
        headers=headers,
        json={"status": "running"},
    )
    assert running.status_code == 200
    failed = client.post(
        f"{base}/tasks/{task_id}/transition",
        headers=headers,
        json={"status": "failed", "error_message": "Simulated provider outage"},
    )
    assert failed.status_code == 200

    dashboard = client.get(f"{base}/owner-dashboard", headers=headers)
    assert dashboard.status_code == 200
    incidents = dashboard.json()["operational_incidents"]
    assert incidents["total"] == 1
    assert incidents["critical"] == 1
    assert incidents["warning"] == 0
    incident = incidents["recent"][0]
    assert incident["type"] == "task_failed"
    assert incident["severity"] == "critical"
    assert incident["resource_id"] == task_id
    assert incident["detail"] == "Simulated provider outage"
    assert incident["occurred_at"]
