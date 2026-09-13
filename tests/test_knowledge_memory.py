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
            "email": "knowledge-founder@example.com",
            "password": "correct horse battery staple",
            "display_name": "Knowledge Founder",
            "organization_name": "Seldrune Knowledge",
            "organization_slug": "seldrune-knowledge",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    organization_id = profile["memberships"][0]["organization"]["id"]
    return token, organization_id


def test_knowledge_search_and_runtime_memory(client: TestClient) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}

    knowledge = client.post(
        f"/api/v1/organizations/{organization_id}/knowledge",
        headers=headers,
        json={
            "title": "Payment reconciliation evidence",
            "content": (
                "Indian merchants often reconcile payment gateway settlements, bank credits, "
                "refunds, and ERP records across separate systems."
            ),
            "kind": "research",
            "tags": ["payments", "reconciliation"],
            "source_type": "internal-research",
            "source_uri": "internal://research/reconciliation",
        },
    )
    assert knowledge.status_code == 201
    knowledge_ref = f"knowledge:{knowledge.json()['id']}"

    memory = client.post(
        f"/api/v1/organizations/{organization_id}/memory",
        headers=headers,
        json={
            "scope": "organization",
            "kind": "fact",
            "key": "Reconciliation priority",
            "content": "Prioritize settlement mismatches and refund exceptions.",
            "importance": 80,
        },
    )
    assert memory.status_code == 201

    search = client.get(
        f"/api/v1/organizations/{organization_id}/knowledge/search",
        headers=headers,
        params={"q": "payment reconciliation", "limit": 5},
    )
    assert search.status_code == 200
    hits = search.json()["hits"]
    assert hits
    assert hits[0]["ref"] == knowledge_ref
    assert hits[0]["source_uri"] == "internal://research/reconciliation"

    agent = client.post(
        f"/api/v1/organizations/{organization_id}/agents",
        headers=headers,
        json={
            "name": "Knowledge R&D Agent",
            "slug": "knowledge-rnd-agent",
            "capabilities": ["research", "analysis"],
            "runtime_config": {"provider": "mock", "model": "mock-v1"},
        },
    )
    assert agent.status_code == 201

    task = client.post(
        f"/api/v1/organizations/{organization_id}/tasks",
        headers=headers,
        json={
            "title": "Research payment reconciliation",
            "objective": "Analyze payment reconciliation automation opportunities in India.",
            "assigned_agent_id": agent.json()["id"],
            "input_data": {"market": "India"},
        },
    )
    assert task.status_code == 201

    execute = client.post(
        f"/api/v1/organizations/{organization_id}/tasks/{task.json()['id']}/execute",
        headers=headers,
    )
    assert execute.status_code == 200
    completed = execute.json()
    assert knowledge_ref in completed["output_data"]["context_refs"]

    memories = client.get(
        f"/api/v1/organizations/{organization_id}/memory",
        headers=headers,
    )
    assert memories.status_code == 200
    result_memories = [
        item
        for item in memories.json()
        if item["kind"] == "result" and item["task_id"] == task.json()["id"]
    ]
    assert len(result_memories) == 1
    assert knowledge_ref in result_memories[0]["metadata_json"]["context_refs"]


def test_agent_scoped_memory_requires_agent_id(client: TestClient) -> None:
    token, organization_id = register_owner(client)
    response = client.post(
        f"/api/v1/organizations/{organization_id}/memory",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "scope": "agent",
            "kind": "working",
            "key": "Missing target",
            "content": "This should fail validation.",
        },
    )
    assert response.status_code == 422
