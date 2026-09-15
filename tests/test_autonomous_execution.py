import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.services.autonomous_execution import runtime_budget_allows_next_step


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
            "email": "autonomy-founder@example.com",
            "password": "correct horse battery staple",
            "display_name": "Autonomy Founder",
            "organization_name": "Seldrune Autonomy",
            "organization_slug": "seldrune-autonomy",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    organization_id = profile["memberships"][0]["organization"]["id"]
    return token, organization_id


def create_agent(
    client: TestClient,
    organization_id: str,
    headers: dict[str, str],
    *,
    name: str,
    slug: str,
    capabilities: list[str],
) -> dict:
    response = client.post(
        f"/api/v1/organizations/{organization_id}/agents",
        headers=headers,
        json={
            "name": name,
            "slug": slug,
            "capabilities": capabilities,
            "runtime_config": {
                "provider": "mock",
                "model": "mock-v1",
            },
        },
    )
    assert response.status_code == 201
    return response.json()


def create_two_step_run(
    client: TestClient,
    organization_id: str,
    headers: dict[str, str],
) -> dict:
    response = client.post(
        f"/api/v1/organizations/{organization_id}/orchestrations",
        headers=headers,
        json={
            "objective": "Research and analyze payment reconciliation automation",
            "context": {"market": "India"},
            "plan": [
                {
                    "title": "Research payment reconciliation",
                    "description": "Collect evidence about reconciliation pain.",
                    "capabilities": ["research"],
                    "priority": 20,
                },
                {
                    "title": "Analyze the research",
                    "description": "Analyze the evidence and recommend next actions.",
                    "capabilities": ["analysis"],
                    "priority": 10,
                },
            ],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_autonomous_execution_runs_steps_and_passes_upstream_context(
    client: TestClient,
) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    create_agent(
        client,
        organization_id,
        headers,
        name="Research Agent",
        slug="research-agent",
        capabilities=["research"],
    )
    create_agent(
        client,
        organization_id,
        headers,
        name="Analysis Agent",
        slug="analysis-agent",
        capabilities=["analysis"],
    )
    run = create_two_step_run(client, organization_id, headers)

    execute = client.post(
        f"/api/v1/organizations/{organization_id}/orchestrations/{run['id']}/execute",
        headers=headers,
        json={},
    )
    assert execute.status_code == 200
    body = execute.json()
    assert body["execution"]["executed_steps"] == 2
    assert body["execution"]["failed_steps"] == 0
    assert body["execution"]["blocked_steps"] == 0
    assert body["run"]["status"] == "succeeded"

    first_task_id = body["run"]["steps"][0]["task_id"]
    second_task_id = body["run"]["steps"][1]["task_id"]
    first_task = client.get(
        f"/api/v1/organizations/{organization_id}/tasks/{first_task_id}",
        headers=headers,
    ).json()
    second_task = client.get(
        f"/api/v1/organizations/{organization_id}/tasks/{second_task_id}",
        headers=headers,
    ).json()

    assert first_task["status"] == "succeeded"
    assert second_task["status"] == "succeeded"
    upstream = second_task["input_data"]["upstream_results"]
    assert len(upstream) == 1
    assert upstream[0]["task_id"] == first_task_id
    assert upstream[0]["output"]["provider"] == "mock"

    resume = client.post(
        f"/api/v1/organizations/{organization_id}/orchestrations/{run['id']}/execute",
        headers=headers,
        json={},
    )
    assert resume.status_code == 200
    resumed = resume.json()["execution"]
    assert resumed["executed_steps"] == 0
    assert resumed["skipped_succeeded_steps"] == 2


def test_autonomous_execution_stops_at_unmatched_dependency(client: TestClient) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    create_agent(
        client,
        organization_id,
        headers,
        name="Research Agent",
        slug="research-only-agent",
        capabilities=["research"],
    )
    run = create_two_step_run(client, organization_id, headers)

    execute = client.post(
        f"/api/v1/organizations/{organization_id}/orchestrations/{run['id']}/execute",
        headers=headers,
        json={},
    )
    assert execute.status_code == 200
    body = execute.json()
    assert body["execution"]["executed_steps"] == 1
    assert body["execution"]["blocked_steps"] == 1
    assert body["execution"]["halted_reason"] == "unmatched_or_unassigned"

    second_task_id = body["run"]["steps"][1]["task_id"]
    second_task = client.get(
        f"/api/v1/organizations/{organization_id}/tasks/{second_task_id}",
        headers=headers,
    ).json()
    assert second_task["status"] == "queued"


def test_runtime_budget_circuit_breaker_boundary() -> None:
    assert runtime_budget_allows_next_step(
        reservation_usd=None,
        recorded_cost_usd=100,
        estimated_next_step_usd=100,
    )
    assert runtime_budget_allows_next_step(
        reservation_usd=0.15,
        recorded_cost_usd=0.10,
        estimated_next_step_usd=0.05,
    )
    assert not runtime_budget_allows_next_step(
        reservation_usd=0.15,
        recorded_cost_usd=0.11,
        estimated_next_step_usd=0.05,
    )
