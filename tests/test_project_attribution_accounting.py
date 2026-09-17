from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.core.orchestration import PlannedStep
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.agent import Agent
from backend.app.models.membership import Membership
from backend.app.models.model_invocation import ModelInvocation
from backend.app.models.organization import Organization
from backend.app.models.organization_kernel import Department, OrganizationProject
from backend.app.models.orchestration import OrchestrationRun, OrchestrationStep
from backend.app.models.task import Task
from backend.app.models.user import User
from backend.app.services.command_recovery import create_recovery_command
from backend.app.services.orchestrator import (
    OrchestrationAttributionError,
    create_orchestration_run,
)
from backend.app.services.portfolio_governor import evaluate_project_execution
from backend.app.services.project_delivery import ProjectDeliveryError, sync_project_delivery_outcome

PASSWORD = "correct horse battery staple"


@pytest.fixture
def accounting_client():
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


def _register_owner(client: TestClient) -> tuple[dict[str, str], str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "v1-founder@example.com",
            "password": PASSWORD,
            "display_name": "V1 Founder",
            "organization_name": "Seldrune V1",
            "organization_slug": "seldrune-v1",
        },
    )
    assert response.status_code == 201
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    return (
        headers,
        profile["memberships"][0]["organization"]["id"],
        profile["user"]["id"],
    )


def _create_project(client: TestClient, headers: dict[str, str], organization_id: str) -> tuple[str, str]:
    department = client.post(
        f"/api/v1/organizations/{organization_id}/departments",
        headers=headers,
        json={"name": "Delivery", "slug": "delivery"},
    )
    assert department.status_code == 201
    department_id = department.json()["id"]
    project = client.post(
        f"/api/v1/organizations/{organization_id}/projects",
        headers=headers,
        json={
            "name": "V1 delivery",
            "slug": "v1-delivery",
            "department_id": department_id,
            "budget_limit_usd": 10,
        },
    )
    assert project.status_code == 201
    assert project.json()["unpriced_model_invocation_count"] == 0
    return project.json()["id"], department_id


def test_manual_task_attribution_billing_rollup_and_owner_correction(accounting_client) -> None:
    client, testing_session = accounting_client
    headers, organization_id, user_id = _register_owner(client)
    project_id, department_id = _create_project(client, headers, organization_id)

    agent = client.post(
        f"/api/v1/organizations/{organization_id}/agents",
        headers=headers,
        json={"name": "Usage Agent", "slug": "usage-agent"},
    )
    assert agent.status_code == 201
    agent_id = agent.json()["id"]
    task = client.post(
        f"/api/v1/organizations/{organization_id}/tasks",
        headers=headers,
        json={
            "title": "Attributed task",
            "objective": "Measure attributed model usage",
            "assigned_agent_id": agent_id,
            "project_id": project_id,
        },
    )
    assert task.status_code == 201
    assert task.json()["project_id"] == project_id

    with testing_session() as session:
        org_id = UUID(organization_id)
        other = Organization(name="Other Org", slug="other-v1-org")
        session.add(other)
        session.flush()
        foreign_project = OrganizationProject(
            organization_id=other.id,
            name="Foreign project",
            slug="foreign-project",
        )
        session.add(foreign_project)
        session.add_all(
            [
                ModelInvocation(
                    organization_id=org_id,
                    task_id=UUID(task.json()["id"]),
                    agent_id=UUID(agent_id),
                    provider="openai",
                    model="priced-model",
                    status="succeeded",
                    input_tokens=10,
                    output_tokens=5,
                    total_tokens=15,
                    estimated_cost_usd=0.02,
                ),
                ModelInvocation(
                    organization_id=org_id,
                    task_id=UUID(task.json()["id"]),
                    agent_id=UUID(agent_id),
                    provider="openai",
                    model="unpriced-model",
                    status="succeeded",
                    input_tokens=20,
                    output_tokens=10,
                    total_tokens=30,
                    estimated_cost_usd=None,
                ),
            ]
        )
        session.commit()
        foreign_project_id = str(foreign_project.id)

    denied = client.post(
        f"/api/v1/organizations/{organization_id}/tasks",
        headers=headers,
        json={
            "title": "Foreign attribution",
            "objective": "Must be rejected",
            "project_id": foreign_project_id,
        },
    )
    assert denied.status_code == 404

    summary = client.get(
        f"/api/v1/organizations/{organization_id}/billing/usage-summary",
        headers=headers,
        params={"project_id": project_id},
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["totals"]["invocation_count"] == 2
    assert body["totals"]["priced_invocation_count"] == 1
    assert body["totals"]["unpriced_invocation_count"] == 1
    assert body["totals"]["known_estimated_cost_usd"] == 0.02
    assert body["by_project"] == [
        {
            "project_id": project_id,
            "department_id": department_id,
            "invocation_count": 2,
            "total_tokens": 45,
            "priced_invocation_count": 1,
            "unpriced_invocation_count": 1,
            "known_estimated_cost_usd": 0.02,
        }
    ]
    assert body["by_department"][0]["department_id"] == department_id

    department_filtered = client.get(
        f"/api/v1/organizations/{organization_id}/billing/invocations",
        headers=headers,
        params={"department_id": department_id},
    )
    assert department_filtered.status_code == 200
    assert department_filtered.json()["returned"] == 2

    with testing_session() as session:
        project = session.get(OrganizationProject, UUID(project_id))
        membership = session.scalar(
            select(Membership).where(
                Membership.organization_id == UUID(organization_id),
                Membership.user_id == UUID(user_id),
            )
        )
        assert project is not None and membership is not None
        project.unpriced_model_invocation_count = 2
        membership.role = "admin"
        session.commit()

    correction_url = (
        f"/api/v1/organizations/{organization_id}/billing/projects/{project_id}/accounting"
    )
    denied_correction = client.patch(
        correction_url,
        headers=headers,
        json={"unpriced_model_invocation_count": 0, "reason": "Resolve provider invoice"},
    )
    assert denied_correction.status_code == 403

    with testing_session() as session:
        membership = session.scalar(
            select(Membership).where(
                Membership.organization_id == UUID(organization_id),
                Membership.user_id == UUID(user_id),
            )
        )
        assert membership is not None
        membership.role = "owner"
        session.commit()

    corrected = client.patch(
        correction_url,
        headers=headers,
        json={
            "budget_spent_usd": 0.07,
            "unpriced_model_invocation_count": 0,
            "reason": "Provider invoice reconciled",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["budget_spent_usd"] == 0.07
    assert corrected.json()["unpriced_model_invocation_count"] == 0


def test_orchestration_and_recovery_tasks_keep_project_attribution(
    accounting_client, monkeypatch
) -> None:
    client, testing_session = accounting_client
    headers, organization_id, user_id = _register_owner(client)
    project_id, _ = _create_project(client, headers, organization_id)

    with testing_session() as session:
        org_id = UUID(organization_id)
        owner_id = UUID(user_id)
        project_uuid = UUID(project_id)
        run = create_orchestration_run(
            session,
            organization_id=org_id,
            created_by_user_id=owner_id,
            objective="Attributed orchestration",
            context={"project_delivery": {"project_id": project_id}},
            plan=[PlannedStep("Do work", "Do attributed work", [])],
            project_id=project_uuid,
        )
        task = session.scalar(
            select(Task)
            .join(OrchestrationStep, OrchestrationStep.task_id == Task.id)
            .where(OrchestrationStep.orchestration_run_id == run.id)
        )
        assert task is not None
        assert task.project_id == project_uuid

        other = Organization(name="Other attribution org", slug="other-attribution-org")
        session.add(other)
        session.flush()
        foreign = OrganizationProject(
            organization_id=other.id,
            name="Foreign",
            slug="foreign",
        )
        session.add(foreign)
        session.flush()
        with pytest.raises(OrchestrationAttributionError):
            create_orchestration_run(
                session,
                organization_id=org_id,
                created_by_user_id=owner_id,
                objective="Invalid attribution",
                context={},
                plan=[],
                project_id=foreign.id,
            )
        session.rollback()

    with testing_session() as session:
        source = OrchestrationRun(
            organization_id=UUID(organization_id),
            created_by_user_id=UUID(user_id),
            objective="Recover project delivery",
            status="succeeded",
            context={"project_delivery": {"project_id": project_id}},
        )
        session.add(source)
        session.flush()

        monkeypatch.setattr(
            "backend.app.services.command_recovery.assess_command_outcome",
            lambda _session, run: SimpleNamespace(
                promotable=False,
                to_dict=lambda: {"verdict": "review", "run_id": str(run.id)},
            ),
        )
        monkeypatch.setattr(
            "backend.app.services.command_recovery.ensure_founding_agents",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            "backend.app.services.command_recovery.consolidate_playbooks",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            "backend.app.services.command_recovery.build_playbook_guidance",
            lambda *args, **kwargs: {},
        )
        monkeypatch.setattr(
            "backend.app.services.command_recovery.build_adaptive_planning_guidance",
            lambda *args, **kwargs: {},
        )
        monkeypatch.setattr(
            "backend.app.services.command_recovery.merge_playbook",
            lambda *args, **kwargs: {},
        )
        monkeypatch.setattr(
            "backend.app.services.command_recovery.build_live_plan",
            lambda *args, **kwargs: SimpleNamespace(
                steps=[PlannedStep("Recover", "Verify recovery", [])],
                metadata={},
                planner_version="test-v1",
            ),
        )
        recovery = create_recovery_command(
            session,
            source_run=source,
            actor_user_id=UUID(user_id),
        )
        recovery_task = session.scalar(
            select(Task)
            .join(OrchestrationStep, OrchestrationStep.task_id == Task.id)
            .where(OrchestrationStep.orchestration_run_id == recovery.id)
        )
        assert recovery_task is not None
        assert recovery_task.project_id == UUID(project_id)


def test_delivery_sync_preserves_unknown_cost_and_blocks_until_corrected(accounting_client) -> None:
    client, testing_session = accounting_client
    headers, organization_id, user_id = _register_owner(client)
    project_id, _ = _create_project(client, headers, organization_id)

    with testing_session() as session:
        org_id = UUID(organization_id)
        owner_id = UUID(user_id)
        project = session.get(OrganizationProject, UUID(project_id))
        assert project is not None
        agent = Agent(
            organization_id=org_id,
            created_by_user_id=owner_id,
            name="Accounting Agent",
            slug="accounting-agent",
        )
        session.add(agent)
        session.flush()
        run = OrchestrationRun(
            organization_id=org_id,
            created_by_user_id=owner_id,
            objective="Reconcile delivery",
            status="succeeded",
            summary={"step_count": 1, "succeeded_steps": 1},
            context={"project_delivery": {"project_id": project_id}},
        )
        session.add(run)
        session.flush()
        task = Task(
            organization_id=org_id,
            project_id=project.id,
            created_by_user_id=owner_id,
            assigned_agent_id=agent.id,
            title="Delivered work",
            objective="Complete project work",
            status="succeeded",
            output_data={"text": "Delivery was verified successfully."},
        )
        session.add(task)
        session.flush()
        session.add(
            OrchestrationStep(
                orchestration_run_id=run.id,
                organization_id=org_id,
                task_id=task.id,
                assigned_agent_id=agent.id,
                sequence=1,
                title="Delivered work",
                objective="Complete project work",
                required_capabilities=[],
                requires_approval=False,
                match_score=100,
            )
        )
        session.add_all(
            [
                ModelInvocation(
                    organization_id=org_id,
                    task_id=task.id,
                    agent_id=agent.id,
                    provider="openai",
                    model="priced",
                    status="succeeded",
                    estimated_cost_usd=0.02,
                ),
                ModelInvocation(
                    organization_id=org_id,
                    task_id=task.id,
                    agent_id=agent.id,
                    provider="openai",
                    model="unpriced",
                    status="succeeded",
                    estimated_cost_usd=None,
                ),
            ]
        )
        project.metadata_json = {
            "budget_reservations": [
                {
                    "command_id": str(run.id),
                    "amount_usd": 0.05,
                    "status": "active",
                }
            ]
        }
        session.flush()

        outcome = sync_project_delivery_outcome(
            session,
            run=run,
            actor_user_id=owner_id,
            project=project,
        )
        assert outcome is not None
        assert project.budget_spent_usd == 0.02
        assert project.unpriced_model_invocation_count == 1
        assert project.metadata_json["delivery_recorded_cost_usd"] is None
        assert project.metadata_json["delivery_known_cost_usd"] == 0.02
        assert project.metadata_json["delivery_unpriced_invocation_count"] == 1
        reconciliation = project.metadata_json["delivery_budget_reconciliation"]
        assert reconciliation["status"] == "reconciled_unpriced"
        assert reconciliation["known_cost_usd"] == 0.02
        assert "variance_usd" not in reconciliation

        decision = evaluate_project_execution(
            project=project,
            run=run,
            delivery_context={"project_id": project_id},
        )
        assert decision["allowed"] is False
        assert decision["accounting_complete"] is False
        assert any("unresolved unpriced" in reason for reason in decision["reasons"])

        other_project = OrganizationProject(
            organization_id=org_id,
            name="Other project",
            slug="other-project",
        )
        session.add(other_project)
        session.flush()
        conflicting_run = OrchestrationRun(
            organization_id=org_id,
            created_by_user_id=owner_id,
            objective="Conflicting delivery",
            status="succeeded",
            context={"project_delivery": {"project_id": project_id}},
        )
        session.add(conflicting_run)
        session.flush()
        conflicting_task = Task(
            organization_id=org_id,
            project_id=other_project.id,
            title="Wrong project",
            objective="Must not contaminate accounting",
            status="succeeded",
            output_data={"text": "Verified."},
        )
        session.add(conflicting_task)
        session.flush()
        session.add(
            OrchestrationStep(
                orchestration_run_id=conflicting_run.id,
                organization_id=org_id,
                task_id=conflicting_task.id,
                sequence=1,
                title="Wrong project",
                objective="Must not contaminate accounting",
                required_capabilities=[],
            )
        )
        session.flush()
        with pytest.raises(ProjectDeliveryError, match="another project"):
            sync_project_delivery_outcome(
                session,
                run=conflicting_run,
                actor_user_id=owner_id,
                project=project,
            )
