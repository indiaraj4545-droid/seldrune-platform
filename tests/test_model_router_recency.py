from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from backend.app.core.modeling import InvocationStatus, ModelProvider
from backend.app.services import model_router_recency as recency_module
from backend.app.services.model_router_recency import (
    build_verified_model_performance_evidence,
)


class _FakeSession:
    def __init__(self, invocations, tasks):
        self.invocations = invocations
        self.tasks = tasks

    def scalars(self, _query):
        return self.invocations

    def get(self, _model, key):
        return self.tasks.get(key)


def test_builder_uses_only_machine_verified_terminal_invocations(monkeypatch) -> None:
    now = datetime(2026, 9, 26, 7, 0, tzinfo=UTC)
    org_id = uuid4()
    verified_task_id = uuid4()
    unverified_task_id = uuid4()
    running_task_id = uuid4()
    tasks = {
        verified_task_id: SimpleNamespace(
            id=verified_task_id,
            organization_id=org_id,
        ),
        unverified_task_id: SimpleNamespace(
            id=unverified_task_id,
            organization_id=org_id,
        ),
        running_task_id: SimpleNamespace(
            id=running_task_id,
            organization_id=org_id,
        ),
    }
    invocations = [
        SimpleNamespace(
            id=uuid4(),
            organization_id=org_id,
            task_id=verified_task_id,
            provider=ModelProvider.OPENAI.value,
            model="gpt-5.6-sol",
            status=InvocationStatus.SUCCEEDED.value,
            created_at=now - timedelta(hours=2),
            completed_at=now - timedelta(hours=1),
        ),
        SimpleNamespace(
            id=uuid4(),
            organization_id=org_id,
            task_id=verified_task_id,
            provider=ModelProvider.OPENAI_COMPATIBLE.value,
            model="local-general",
            status=InvocationStatus.FAILED.value,
            created_at=now - timedelta(hours=4),
            completed_at=now - timedelta(hours=3),
        ),
        SimpleNamespace(
            id=uuid4(),
            organization_id=org_id,
            task_id=unverified_task_id,
            provider=ModelProvider.OPENAI.value,
            model="gpt-5.6-sol",
            status=InvocationStatus.SUCCEEDED.value,
            created_at=now - timedelta(minutes=30),
            completed_at=now - timedelta(minutes=20),
        ),
        SimpleNamespace(
            id=uuid4(),
            organization_id=org_id,
            task_id=running_task_id,
            provider=ModelProvider.OPENAI.value,
            model="gpt-5.6-sol",
            status=InvocationStatus.RUNNING.value,
            created_at=now - timedelta(minutes=5),
            completed_at=None,
        ),
    ]

    def fake_verify(_session, *, task):
        if task.id == verified_task_id:
            return True, "verified_tool_receipt", ["receipt:verified"]
        return False, "unverified", []

    monkeypatch.setattr(
        recency_module,
        "verify_task_completion_evidence",
        fake_verify,
    )
    evidence = build_verified_model_performance_evidence(
        _FakeSession(invocations, tasks),
        organization_id=org_id,
        now=now,
    )

    assert len(evidence) == 2
    assert {item.provider for item in evidence} == {
        ModelProvider.OPENAI,
        ModelProvider.OPENAI_COMPATIBLE,
    }
    assert {item.succeeded for item in evidence} == {True, False}
    assert {item.age_seconds for item in evidence} == {3600, 10800}
    assert all(item.verified for item in evidence)
    assert all("receipt:verified" in item.evidence_refs for item in evidence)
    assert all(
        any(ref.startswith("model-invocation:") for ref in item.evidence_refs)
        for item in evidence
    )
