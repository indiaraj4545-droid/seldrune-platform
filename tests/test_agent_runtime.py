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
            "email": "runtime-founder@example.com",
            "password": "correct horse battery staple",
            "display_name": "Runtime Founder",
            "organization_name": "Seldrune Runtime",
            "organization_slug": "seldrune-runtime",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    profile = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    organization_id = profile["memberships"][0]["organization"]["id"]
    return token, organization_id


def create_runtime_task(client: TestClient, token: str, organization_id: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    agent_response = client.post(
        f"/api/v1/organizations/{organization_id}/agents",
        headers=headers,
        json={
            "name": "R&D Runtime Agent",
            "slug": "rnd-runtime-agent",
            "description": "Executes research tasks.",
            "capabilities": ["research", "analysis"],
            "runtime_config": {
                "provider": "mock",
                "model": "mock-v1",
                "input_cost_per_million": 1.0,
                "output_cost_per_million": 2.0,
            },
        },
    )
    assert agent_response.status_code == 201
    agent = agent_response.json()

    task_response = client.post(
        f"/api/v1/organizations/{organization_id}/tasks",
        headers=headers,
        json={
            "title": "Validate reconciliation pain",
            "objective": "Find evidence that payment reconciliation is painful.",
            "priority": 20,
            "input_data": {"market": "India"},
            "assigned_agent_id": agent["id"],
        },
    )
    assert task_response.status_code == 201
    return task_response.json()


def test_mock_agent_runtime_executes_task_and_records_usage(client: TestClient) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    task = create_runtime_task(client, token, organization_id)

    execute = client.post(
        f"/api/v1/organizations/{organization_id}/tasks/{task['id']}/execute",
        headers=headers,
    )
    assert execute.status_code == 200
    completed = execute.json()
    assert completed["status"] == "succeeded"
    assert completed["output_data"]["provider"] == "mock"
    assert completed["output_data"]["model"] == "mock-v1"
    assert completed["output_data"]["usage"]["total_tokens"] > 0
    assert "payment reconciliation" in completed["output_data"]["text"].lower()

    invocations = client.get(
        f"/api/v1/organizations/{organization_id}/model-invocations",
        headers=headers,
    )
    assert invocations.status_code == 200
    invocation = invocations.json()[0]
    assert invocation["status"] == "succeeded"
    assert invocation["provider"] == "mock"
    assert invocation["total_tokens"] > 0
    assert invocation["estimated_cost_usd"] is not None

    events = client.get(
        f"/api/v1/organizations/{organization_id}/tasks/{task['id']}/events",
        headers=headers,
    )
    assert events.status_code == 200
    event_types = [event["event_type"] for event in events.json()]
    assert "agent.runtime.started" in event_types
    assert "agent.runtime.completed" in event_types


def test_unassigned_task_cannot_execute(client: TestClient) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    task_response = client.post(
        f"/api/v1/organizations/{organization_id}/tasks",
        headers=headers,
        json={
            "title": "Unassigned task",
            "objective": "Wait for a matching agent.",
            "input_data": {},
        },
    )
    assert task_response.status_code == 201

    execute = client.post(
        f"/api/v1/organizations/{organization_id}/tasks/{task_response.json()['id']}/execute",
        headers=headers,
    )
    assert execute.status_code == 409
