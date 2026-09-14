from tests.test_autonomous_execution import client as _client  # noqa: F401
from tests.test_autonomous_execution import register_owner


def _headers_and_org(client):
    token, organization_id = register_owner(client)
    return {"Authorization": f"Bearer {token}"}, organization_id


def _create_fixture_connector(client, organization_id, headers, *, approval_mode="never"):
    response = client.post(
        f"/api/v1/organizations/{organization_id}/research/connectors",
        headers=headers,
        json={
            "name": "Evidence Fixture",
            "slug": "evidence-fixture",
            "provider": "fixture",
            "approval_mode": approval_mode,
            "config": {
                "documents": [
                    {
                        "title": "Payment reconciliation evidence",
                        "content": (
                            "Payment reconciliation teams compare gateway settlements, "
                            "bank credits, refunds, and ERP records for mismatches."
                        ),
                        "uri": "fixture://payments/reconciliation",
                    }
                ]
            },
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_approved_research_command(client, organization_id, headers):
    created = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands",
        headers=headers,
        json={
            "objective": (
                "Create exactly one step to research payment reconciliation automation"
            )
        },
    )
    assert created.status_code == 201
    command = created.json()
    assert len(command["steps"]) == 1
    assert command["steps"][0]["required_capabilities"] == ["research"]
    approved = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands/{command['id']}/approve",
        headers=headers,
    )
    assert approved.status_code == 200
    return command


def test_owner_research_collects_provenance_before_agent_execution(_client) -> None:  # noqa: F811
    client = _client
    headers, organization_id = _headers_and_org(client)
    _create_fixture_connector(client, organization_id, headers)
    command = _create_approved_research_command(client, organization_id, headers)

    executed = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands/{command['id']}/execute",
        headers=headers,
        json={},
    )
    assert executed.status_code == 200
    payload = executed.json()
    preflight = payload["run"]["summary"]["research_preflight"]
    assert preflight["research_steps"] == 1
    assert preflight["source_count"] == 1
    assert len(preflight["refs"]) == 1

    task_id = payload["run"]["steps"][0]["task_id"]
    task = client.get(
        f"/api/v1/organizations/{organization_id}/tasks/{task_id}",
        headers=headers,
    )
    assert task.status_code == 200
    task_payload = task.json()
    assert task_payload["input_data"]["research_evidence"]["source_count"] == 1
    assert preflight["refs"][0] in task_payload["output_data"]["context_refs"]


def test_approval_required_connector_is_not_auto_executed(_client) -> None:  # noqa: F811
    client = _client
    headers, organization_id = _headers_and_org(client)
    _create_fixture_connector(
        client,
        organization_id,
        headers,
        approval_mode="always",
    )
    command = _create_approved_research_command(client, organization_id, headers)

    executed = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands/{command['id']}/execute",
        headers=headers,
        json={},
    )
    assert executed.status_code == 200
    preflight = executed.json()["run"]["summary"]["research_preflight"]
    assert preflight["source_count"] == 0
    assert preflight["approval_blocked_connectors"] == 1
    assert preflight["sessions"] == []


def test_reexecuting_completed_command_reuses_research_session(_client) -> None:  # noqa: F811
    client = _client
    headers, organization_id = _headers_and_org(client)
    _create_fixture_connector(client, organization_id, headers)
    command = _create_approved_research_command(client, organization_id, headers)
    execute_url = (
        f"/api/v1/organizations/{organization_id}/owner-commands/{command['id']}/execute"
    )

    first = client.post(execute_url, headers=headers, json={})
    assert first.status_code == 200
    first_preflight = first.json()["run"]["summary"]["research_preflight"]
    assert len(first_preflight["sessions"]) == 1

    second = client.post(execute_url, headers=headers, json={})
    assert second.status_code == 200
    second_preflight = second.json()["run"]["summary"]["research_preflight"]
    assert second_preflight["sessions"] == first_preflight["sessions"]

    sessions = client.get(
        f"/api/v1/organizations/{organization_id}/research/sessions",
        headers=headers,
    )
    assert sessions.status_code == 200
    assert len(sessions.json()) == 1
