from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.core.rbac import Permission, Role, has_permission
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.agent import Agent
from backend.app.models.membership import Membership
from backend.app.models.model_invocation import ModelInvocation
from backend.app.models.organization import Organization
from backend.app.models.task import Task


@pytest.fixture
def billing_client():
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
    with TestClient(app) as client:
        yield client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def register_owner(client: TestClient) -> tuple[dict[str, str], str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "billing-founder@example.com",
            "password": "correct horse battery staple",
            "display_name": "Billing Founder",
            "organization_name": "Seldrune Billing",
            "organization_slug": "seldrune-billing",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    organization_id = profile["memberships"][0]["organization"]["id"]
    return headers, organization_id, profile["user"]["id"]


def seed_usage(testing_session, organization_id: str, user_id: str) -> dict[str, str]:
    base_time = datetime(2026, 9, 17, 9, 0, tzinfo=UTC)
    with testing_session() as session:
        org_id = UUID(organization_id)
        owner_id = UUID(user_id)
        agent = Agent(
            organization_id=org_id,
            created_by_user_id=owner_id,
            name="Billing Agent",
            slug="billing-agent",
        )
        session.add(agent)
        session.flush()

        tasks = [
            Task(
                organization_id=org_id,
                created_by_user_id=owner_id,
                assigned_agent_id=agent.id,
                title=f"Billing task {index}",
                objective="Measure model usage",
            )
            for index in range(1, 4)
        ]
        session.add_all(tasks)
        session.flush()

        first = ModelInvocation(
            organization_id=org_id,
            task_id=tasks[0].id,
            agent_id=agent.id,
            provider="openai",
            model="gpt-test",
            status="succeeded",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=0.01,
            latency_ms=100,
            created_at=base_time,
            completed_at=base_time + timedelta(seconds=1),
        )
        second = ModelInvocation(
            organization_id=org_id,
            task_id=tasks[1].id,
            agent_id=agent.id,
            provider="openai",
            model="gpt-test",
            status="succeeded",
            input_tokens=200,
            output_tokens=100,
            total_tokens=300,
            estimated_cost_usd=None,
            latency_ms=200,
            created_at=base_time + timedelta(minutes=1),
            completed_at=base_time + timedelta(minutes=1, seconds=1),
        )
        third = ModelInvocation(
            organization_id=org_id,
            task_id=tasks[2].id,
            agent_id=agent.id,
            provider="mock",
            model="mock-v1",
            status="failed",
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            estimated_cost_usd=None,
            latency_ms=None,
            created_at=base_time + timedelta(minutes=2),
            completed_at=base_time + timedelta(minutes=2, seconds=1),
        )

        other = Organization(name="Other Billing Org", slug="other-billing-org")
        session.add(other)
        session.flush()
        other_agent = Agent(organization_id=other.id, name="Other Agent", slug="other-agent")
        session.add(other_agent)
        session.flush()
        other_task = Task(
            organization_id=other.id,
            assigned_agent_id=other_agent.id,
            title="Other task",
            objective="Must remain isolated",
        )
        session.add(other_task)
        session.flush()
        other_invocation = ModelInvocation(
            organization_id=other.id,
            task_id=other_task.id,
            agent_id=other_agent.id,
            provider="openai",
            model="gpt-test",
            status="succeeded",
            input_tokens=999,
            output_tokens=999,
            total_tokens=1998,
            estimated_cost_usd=99.0,
            latency_ms=999,
            created_at=base_time + timedelta(minutes=3),
        )

        session.add_all([first, second, third, other_invocation])
        session.commit()
        return {
            "first": str(first.id),
            "second": str(second.id),
            "third": str(third.id),
            "agent_id": str(agent.id),
            "task_id": str(tasks[1].id),
            "base_time": base_time.isoformat(),
        }


def test_billing_summary_filters_pagination_and_unpriced_usage(billing_client) -> None:
    client, testing_session = billing_client
    headers, organization_id, user_id = register_owner(client)
    seeded = seed_usage(testing_session, organization_id, user_id)

    summary = client.get(
        f"/api/v1/organizations/{organization_id}/billing/usage-summary",
        headers=headers,
    )
    assert summary.status_code == 200
    totals = summary.json()["totals"]
    assert totals == {
        "invocation_count": 3,
        "succeeded_count": 2,
        "failed_count": 1,
        "running_count": 0,
        "input_tokens": 300,
        "output_tokens": 150,
        "total_tokens": 450,
        "priced_invocation_count": 1,
        "unpriced_invocation_count": 2,
        "known_estimated_cost_usd": 0.01,
        "average_latency_ms": 150.0,
    }
    assert summary.json()["by_provider_model"] == [
        {
            "provider": "mock",
            "model": "mock-v1",
            "invocation_count": 1,
            "total_tokens": 0,
            "priced_invocation_count": 0,
            "unpriced_invocation_count": 1,
            "known_estimated_cost_usd": 0.0,
        },
        {
            "provider": "openai",
            "model": "gpt-test",
            "invocation_count": 2,
            "total_tokens": 450,
            "priced_invocation_count": 1,
            "unpriced_invocation_count": 1,
            "known_estimated_cost_usd": 0.01,
        },
    ]

    page = client.get(
        f"/api/v1/organizations/{organization_id}/billing/invocations?limit=2",
        headers=headers,
    )
    assert page.status_code == 200
    assert [item["id"] for item in page.json()["items"]] == [seeded["third"], seeded["second"]]

    second_page = client.get(
        f"/api/v1/organizations/{organization_id}/billing/invocations?limit=2&offset=2",
        headers=headers,
    )
    assert [item["id"] for item in second_page.json()["items"]] == [seeded["first"]]

    openai_only = client.get(
        f"/api/v1/organizations/{organization_id}/billing/invocations",
        headers=headers,
        params={"provider": "openai"},
    )
    assert [item["id"] for item in openai_only.json()["items"]] == [
        seeded["second"],
        seeded["first"],
    ]

    task_only = client.get(
        f"/api/v1/organizations/{organization_id}/billing/invocations",
        headers=headers,
        params={"task_id": seeded["task_id"]},
    )
    assert [item["id"] for item in task_only.json()["items"]] == [seeded["second"]]

    created_from = datetime.fromisoformat(seeded["base_time"]) + timedelta(minutes=1)
    recent = client.get(
        f"/api/v1/organizations/{organization_id}/billing/usage-summary",
        headers=headers,
        params={"created_from": created_from.isoformat()},
    )
    assert recent.status_code == 200
    assert recent.json()["totals"]["invocation_count"] == 2
    assert recent.json()["totals"]["known_estimated_cost_usd"] == 0.0

    invalid_window = client.get(
        f"/api/v1/organizations/{organization_id}/billing/usage-summary",
        headers=headers,
        params={
            "created_from": (created_from + timedelta(minutes=5)).isoformat(),
            "created_to": created_from.isoformat(),
        },
    )
    assert invalid_window.status_code == 400

    assert client.get(
        f"/api/v1/organizations/{organization_id}/billing/invocations?limit=501",
        headers=headers,
    ).status_code == 422
    assert client.get(
        f"/api/v1/organizations/{organization_id}/billing/invocations?offset=-1",
        headers=headers,
    ).status_code == 422


def test_billing_rbac_and_tenant_isolation(billing_client) -> None:
    assert has_permission(Role.OWNER, Permission.BILLING_READ)
    assert has_permission(Role.ADMIN, Permission.BILLING_READ)
    assert has_permission(Role.AUDITOR, Permission.BILLING_READ)
    assert not has_permission(Role.MEMBER, Permission.BILLING_READ)

    client, testing_session = billing_client
    headers, organization_id, user_id = register_owner(client)
    seed_usage(testing_session, organization_id, user_id)

    with testing_session() as session:
        membership = session.scalar(
            select(Membership).where(
                Membership.organization_id == UUID(organization_id),
                Membership.user_id == UUID(user_id),
            )
        )
        assert membership is not None
        membership.role = "member"
        session.commit()

    denied = client.get(
        f"/api/v1/organizations/{organization_id}/billing/usage-summary",
        headers=headers,
    )
    assert denied.status_code == 403

    with testing_session() as session:
        membership = session.scalar(
            select(Membership).where(
                Membership.organization_id == UUID(organization_id),
                Membership.user_id == UUID(user_id),
            )
        )
        assert membership is not None
        membership.role = "auditor"
        session.commit()

    allowed = client.get(
        f"/api/v1/organizations/{organization_id}/billing/usage-summary",
        headers=headers,
    )
    assert allowed.status_code == 200
    assert allowed.json()["totals"]["invocation_count"] == 3
    assert allowed.json()["totals"]["total_tokens"] == 450
    assert allowed.json()["totals"]["known_estimated_cost_usd"] == 0.01
