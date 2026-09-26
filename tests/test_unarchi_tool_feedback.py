from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.task import Task
from backend.app.models.tool_run import ToolRun
from backend.app.services.unarchi_engine import UnarchiEngine
from backend.app.services.unarchi_tool_feedback import (
    UnarchiToolFeedbackError,
    feed_verified_tool_task,
)


@pytest.fixture
def session_factory():
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
    yield testing_session
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(session_factory) -> TestClient:
    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _register_owner(client: TestClient) -> tuple[dict[str, str], UUID, UUID]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "unarchi-feedback@example.com",
            "password": "correct horse battery staple",
            "display_name": "UNARCHI Feedback Owner",
            "organization_name": "UNARCHI Feedback",
            "organization_slug": "unarchi-feedback",
        },
    )
    assert response.status_code == 201
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    return (
        headers,
        UUID(profile["memberships"][0]["organization"]["id"]),
        UUID(profile["user"]["id"]),
    )


def _create_tool(
    client: TestClient,
    headers: dict[str, str],
    organization_id: UUID,
) -> UUID:
    response = client.post(
        f"/api/v1/organizations/{organization_id}/tools",
        headers=headers,
        json={
            "name": "UNARCHI Echo Feedback",
            "slug": "unarchi-echo-feedback",
            "provider": "internal",
            "action_name": "echo",
            "risk_level": "low",
            "approval_mode": "never",
        },
    )
    assert response.status_code == 201
    return UUID(response.json()["id"])


def _verified_task(
    session: Session,
    *,
    organization_id: UUID,
    owner_id: UUID,
    tool_id: UUID,
    receipt_override: str | None = None,
) -> tuple[Task, ToolRun]:
    task = Task(
        organization_id=organization_id,
        created_by_user_id=owner_id,
        title="Consume verified tool feedback",
        objective="Use verified tool output to update bounded cognitive state.",
        status="succeeded",
        input_data={
            "tool_request": {
                "slug": "unarchi-echo-feedback",
                "input": {"message": "verified"},
            }
        },
    )
    session.add(task)
    session.flush()

    run = ToolRun(
        organization_id=organization_id,
        tool_id=tool_id,
        task_id=task.id,
        requested_by_user_id=owner_id,
        status="succeeded",
        input_data={"message": "verified"},
        output_data={"echo": {"message": "verified"}},
    )
    session.add(run)
    session.flush()

    receipt_id = receipt_override or f"tool-run:{run.id}"
    task.output_data = {
        "execution_type": "tool",
        "tool_slug": "unarchi-echo-feedback",
        "evidence": {
            "receipt_id": receipt_id,
            "tool_run_id": str(run.id),
        },
    }
    session.commit()
    session.refresh(task)
    session.refresh(run)
    return task, run


def test_verified_gateway_receipt_updates_unarchi_once(
    client: TestClient,
    session_factory,
) -> None:
    headers, organization_id, owner_id = _register_owner(client)
    tool_id = _create_tool(client, headers, organization_id)
    engine = UnarchiEngine()

    with session_factory() as session:
        task, run = _verified_task(
            session,
            organization_id=organization_id,
            owner_id=owner_id,
            tool_id=tool_id,
        )
        before_count = engine.state.experience_count
        first = feed_verified_tool_task(
            session,
            engine=engine,
            task=task,
            predicted_success=0.7,
        )
        after_first = engine.state.experience_count
        second = feed_verified_tool_task(
            session,
            engine=engine,
            task=task,
            predicted_success=0.7,
        )

        assert first == second
        assert after_first == before_count + 1
        assert engine.state.experience_count == after_first
        assert engine.snapshot()["verified_tool_outcome_count"] == 1
        assert first.receipt_id == f"tool-run:{run.id}"
        assert first.tool_run_id == str(run.id)
        assert f"receipt:tool-run:{run.id}" in first.source_refs
        assert f"tool-run:{run.id}" in first.source_refs

        durable = next(
            item
            for item in engine.persistent_memory
            if item.id == first.persistent_memory_id
        )
        assert durable.kind == "verified_tool_outcome"
        assert run.status == "succeeded"
        assert run.output_data == {"echo": {"message": "verified"}}


def test_tampered_gateway_receipt_cannot_change_unarchi_state(
    client: TestClient,
    session_factory,
) -> None:
    headers, organization_id, owner_id = _register_owner(client)
    tool_id = _create_tool(client, headers, organization_id)
    engine = UnarchiEngine()
    before = engine.export_state()

    with session_factory() as session:
        task, _run = _verified_task(
            session,
            organization_id=organization_id,
            owner_id=owner_id,
            tool_id=tool_id,
            receipt_override="tampered-receipt",
        )
        with pytest.raises(
            UnarchiToolFeedbackError,
            match="tool_receipt_mismatch",
        ):
            feed_verified_tool_task(
                session,
                engine=engine,
                task=task,
            )

    assert engine.export_state() == before
