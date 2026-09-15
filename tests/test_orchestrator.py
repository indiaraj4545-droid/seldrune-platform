from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.agent import Agent
from backend.app.services.orchestrator import select_best_agent


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
            "email": "founder@example.com",
            "password": "correct horse battery staple",
            "display_name": "Founder",
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
            "runtime_config": {},
        },
    )
    assert response.status_code == 201
    return response.json()


def test_orchestrator_decomposes_and_matches_agents(client: TestClient) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}

    research = create_agent(
        client,
        organization_id,
        headers,
        name="R&D Agent",
        slug="rnd-agent",
        capabilities=["research", "analysis"],
    )
    engineering = create_agent(
        client,
        organization_id,
        headers,
        name="Engineering Agent",
        slug="engineering-agent",
        capabilities=["engineering", "validation"],
    )

    response = client.post(
        f"/api/v1/organizations/{organization_id}/orchestrations",
        headers=headers,
        json={
            "objective": "Build an AI workflow for payment reconciliation",
            "context": {"market": "India"},
            "plan": [
                {
                    "title": "Research reconciliation pain",
                    "description": "Find evidence and current solutions.",
                    "capabilities": ["research"],
                    "priority": 30,
                },
                {
                    "title": "Build prototype",
                    "description": "Implement the first working prototype.",
                    "capabilities": ["engineering"],
                    "priority": 20,
                },
                {
                    "title": "Legal review",
                    "description": "Review regulatory constraints.",
                    "capabilities": ["legal"],
                    "priority": 10,
                },
            ],
        },
    )
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "active"
    assert run["summary"]["step_count"] == 3
    assert run["summary"]["matched_steps"] == 2
    assert run["summary"]["unmatched_steps"] == 1
    assert run["summary"]["agent_routing"]["mode"] == "evidence-weighted-v1"
    assert run["summary"]["agent_routing"]["agents_with_completed_evidence"] == 0
    assert [step["assigned_agent_id"] for step in run["steps"]] == [
        research["id"],
        engineering["id"],
        None,
    ]
    assert [step["match_score"] for step in run["steps"]] == [100, 100, 0]


def test_default_planner_creates_build_lifecycle(client: TestClient) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        f"/api/v1/organizations/{organization_id}/orchestrations",
        headers=headers,
        json={"objective": "Create a software platform for vendor payroll"},
    )
    assert response.status_code == 201
    run = response.json()
    assert run["planner_version"] == "deterministic-v1"
    assert len(run["steps"]) == 5
    assert run["steps"][0]["required_capabilities"] == ["research"]
    assert run["steps"][-1]["required_capabilities"] == ["validation"]


def test_agent_selection_prefers_verified_success_evidence() -> None:
    organization_id = uuid4()
    reliable = Agent(
        id=uuid4(),
        organization_id=organization_id,
        name="Reliable Researcher",
        slug="reliable-researcher",
        status="active",
        capabilities=["research", "analysis"],
        runtime_config={},
    )
    unproven = Agent(
        id=uuid4(),
        organization_id=organization_id,
        name="Unproven Researcher",
        slug="unproven-researcher",
        status="active",
        capabilities=["research", "analysis"],
        runtime_config={},
    )
    selected, capability_score = select_best_agent(
        [unproven, reliable],
        ["research"],
        {
            reliable.id: {
                "assigned_tasks": 5,
                "completed_tasks": 5,
                "succeeded_tasks": 5,
                "success_rate": 1.0,
            },
            unproven.id: {
                "assigned_tasks": 0,
                "completed_tasks": 0,
                "succeeded_tasks": 0,
                "success_rate": 0.0,
            },
        },
    )
    assert selected is reliable
    assert capability_score == 100


def test_agent_selection_prefers_higher_verified_success_rate() -> None:
    organization_id = uuid4()
    strong = Agent(
        id=uuid4(),
        organization_id=organization_id,
        name="Strong Analyst",
        slug="strong-analyst",
        status="active",
        capabilities=["analysis"],
        runtime_config={},
    )
    weak = Agent(
        id=uuid4(),
        organization_id=organization_id,
        name="Weak Analyst",
        slug="weak-analyst",
        status="active",
        capabilities=["analysis"],
        runtime_config={},
    )
    selected, _ = select_best_agent(
        [weak, strong],
        ["analysis"],
        {
            strong.id: {
                "assigned_tasks": 10,
                "completed_tasks": 10,
                "succeeded_tasks": 9,
                "success_rate": 0.9,
            },
            weak.id: {
                "assigned_tasks": 10,
                "completed_tasks": 10,
                "succeeded_tasks": 4,
                "success_rate": 0.4,
            },
        },
    )
    assert selected is strong
