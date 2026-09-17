import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app


@pytest.fixture
def client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def register_owner(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner@example.com",
            "password": "correct horse battery staple",
            "display_name": "Owner",
            "organization_name": "Seldrune",
            "organization_slug": "seldrune",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    organization_id = profile["memberships"][0]["organization"]["id"]
    return token, organization_id


def test_agent_registry_and_task_lifecycle(client: TestClient) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}

    agent_response = client.post(
        f"/api/v1/organizations/{organization_id}/agents",
        headers=headers,
        json={
            "name": "R&D Agent",
            "slug": "rnd-agent",
            "description": "Researches markets and validates opportunities.",
            "capabilities": ["research", "analysis", "experiments"],
            "runtime_config": {"model_class": "reasoning"},
        },
    )
    assert agent_response.status_code == 201
    agent = agent_response.json()
    assert agent["status"] == "active"

    task_response = client.post(
        f"/api/v1/organizations/{organization_id}/tasks",
        headers=headers,
        json={
            "title": "Find reconciliation pain",
            "objective": "Research payment reconciliation problems and evidence.",
            "priority": 20,
            "input_data": {"market": "India"},
            "assigned_agent_id": agent["id"],
        },
    )
    assert task_response.status_code == 201
    task = task_response.json()
    assert task["status"] == "assigned"

    running = client.post(
        f"/api/v1/organizations/{organization_id}/tasks/{task['id']}/transition",
        headers=headers,
        json={"status": "running"},
    )
    assert running.status_code == 200
    assert running.json()["started_at"] is not None

    completed = client.post(
        f"/api/v1/organizations/{organization_id}/tasks/{task['id']}/transition",
        headers=headers,
        json={
            "status": "succeeded",
            "output_data": {"pain_score": 86, "recommendation": "prototype"},
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "succeeded"
    assert completed.json()["output_data"]["pain_score"] == 86

    events = client.get(
        f"/api/v1/organizations/{organization_id}/tasks/{task['id']}/events",
        headers=headers,
    )
    assert events.status_code == 200
    event_types = [event["event_type"] for event in events.json()]
    assert event_types == [
        "task.created",
        "task.status_changed",
        "task.status_changed",
    ]


def test_invalid_task_transition_returns_conflict(client: TestClient) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}

    task_response = client.post(
        f"/api/v1/organizations/{organization_id}/tasks",
        headers=headers,
        json={
            "title": "Queued research",
            "objective": "Wait for an agent assignment.",
        },
    )
    assert task_response.status_code == 201
    task_id = task_response.json()["id"]

    invalid = client.post(
        f"/api/v1/organizations/{organization_id}/tasks/{task_id}/transition",
        headers=headers,
        json={"status": "succeeded", "output_data": {"unexpected": True}},
    )
    assert invalid.status_code == 409


def test_agent_registry_lifecycle_is_audited_and_preserves_existing_tasks(
    client: TestClient,
) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{organization_id}/agents",
        headers=headers,
        json={
            "name": "Operations Agent",
            "slug": "operations-agent",
            "description": "Initial description",
            "capabilities": ["operations"],
            "runtime_config": {"model_class": "fast"},
        },
    )
    assert created.status_code == 201
    agent = created.json()

    fetched = client.get(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}",
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == agent["id"]

    updated = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}",
        headers=headers,
        json={
            "name": "Operations Control Agent",
            "description": None,
            "capabilities": ["operations", "monitoring"],
            "runtime_config": {"model_class": "reasoning", "temperature": 0},
        },
    )
    assert updated.status_code == 200
    updated_agent = updated.json()
    assert updated_agent["name"] == "Operations Control Agent"
    assert updated_agent["description"] is None
    assert updated_agent["capabilities"] == ["operations", "monitoring"]
    assert updated_agent["runtime_config"]["model_class"] == "reasoning"

    existing_task = client.post(
        f"/api/v1/organizations/{organization_id}/tasks",
        headers=headers,
        json={
            "title": "Existing assigned task",
            "objective": "Remain assigned when the agent is disabled.",
            "assigned_agent_id": agent["id"],
        },
    )
    assert existing_task.status_code == 201
    existing_task_body = existing_task.json()
    assert existing_task_body["status"] == "assigned"

    disabled = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}/status",
        headers=headers,
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"

    preserved = client.get(
        f"/api/v1/organizations/{organization_id}/tasks/{existing_task_body['id']}",
        headers=headers,
    )
    assert preserved.status_code == 200
    assert preserved.json()["assigned_agent_id"] == agent["id"]
    assert preserved.json()["status"] == "assigned"

    blocked_create = client.post(
        f"/api/v1/organizations/{organization_id}/tasks",
        headers=headers,
        json={
            "title": "Blocked assignment",
            "objective": "A disabled agent must not receive new work.",
            "assigned_agent_id": agent["id"],
        },
    )
    assert blocked_create.status_code == 409

    queued = client.post(
        f"/api/v1/organizations/{organization_id}/tasks",
        headers=headers,
        json={
            "title": "Queued task",
            "objective": "Stay queued until an active agent is available.",
        },
    )
    assert queued.status_code == 201
    blocked_assign = client.post(
        f"/api/v1/organizations/{organization_id}/tasks/{queued.json()['id']}/assign",
        headers=headers,
        json={"agent_id": agent["id"]},
    )
    assert blocked_assign.status_code == 409

    update_audit = client.get(
        f"/api/v1/organizations/{organization_id}/audit-log?action=agent.updated",
        headers=headers,
    )
    assert update_audit.status_code == 200
    update_events = update_audit.json()["events"]
    assert len(update_events) == 1
    assert update_events[0]["resource_id"] == agent["id"]
    assert update_events[0]["details"]["changed_fields"] == [
        "name",
        "description",
        "capabilities",
        "runtime_config",
    ]

    status_audit = client.get(
        f"/api/v1/organizations/{organization_id}/audit-log?action=agent.status_changed",
        headers=headers,
    )
    assert status_audit.status_code == 200
    status_events = status_audit.json()["events"]
    assert len(status_events) == 1
    assert status_events[0]["resource_id"] == agent["id"]
    assert status_events[0]["details"] == {"from": "active", "to": "disabled"}


def test_agent_read_is_tenant_scoped(client: TestClient) -> None:
    first_token, first_organization_id = register_owner(client)
    first_headers = {"Authorization": f"Bearer {first_token}"}
    created = client.post(
        f"/api/v1/organizations/{first_organization_id}/agents",
        headers=first_headers,
        json={"name": "Private Agent", "slug": "private-agent"},
    )
    assert created.status_code == 201
    agent_id = created.json()["id"]

    second = client.post(
        "/api/v1/auth/register",
        json={
            "email": "second-owner@example.com",
            "password": "correct horse battery staple",
            "display_name": "Second Owner",
            "organization_name": "Second Organization",
            "organization_slug": "second-organization",
        },
    )
    assert second.status_code == 201
    second_token = second.json()["access_token"]
    second_headers = {"Authorization": f"Bearer {second_token}"}
    second_profile = client.get("/api/v1/auth/me", headers=second_headers).json()
    second_organization_id = second_profile["memberships"][0]["organization"]["id"]

    hidden = client.get(
        f"/api/v1/organizations/{second_organization_id}/agents/{agent_id}",
        headers=second_headers,
    )
    assert hidden.status_code == 404
