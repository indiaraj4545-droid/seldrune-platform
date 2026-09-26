from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.modeling import (
    InvocationStatus,
    ModelProvider,
    ModelRoutePerformanceEvidence,
)
from backend.app.models.model_invocation import ModelInvocation
from backend.app.models.task import Task
from backend.app.services.cognitive_evidence import verify_task_completion_evidence


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def build_verified_model_performance_evidence(
    session: Session,
    *,
    organization_id: UUID,
    now: datetime | None = None,
    max_history: int = 200,
) -> tuple[ModelRoutePerformanceEvidence, ...]:
    """
    Build router evidence only from invocations attached to verified task outcomes.

    Failed model attempts may still count as negative evidence when the task later
    reaches a separately verified outcome through a fallback path. Running or
    unverified task history never enters the router trust signal.
    """
    if max_history <= 0:
        raise ValueError("max_history must be positive")

    observed_now = _utc(now or datetime.now(UTC))
    invocations = list(
        session.scalars(
            select(ModelInvocation)
            .where(ModelInvocation.organization_id == organization_id)
            .order_by(ModelInvocation.created_at.desc())
            .limit(max_history)
        )
    )

    evidence: list[ModelRoutePerformanceEvidence] = []
    for invocation in invocations:
        if invocation.status not in {
            InvocationStatus.SUCCEEDED.value,
            InvocationStatus.FAILED.value,
        }:
            continue
        task = session.get(Task, invocation.task_id)
        if task is None or task.organization_id != organization_id:
            continue
        verified, reason, refs = verify_task_completion_evidence(
            session,
            task=task,
        )
        if not verified:
            continue
        try:
            provider = ModelProvider(invocation.provider)
        except ValueError:
            continue

        observed_at = _utc(invocation.completed_at or invocation.created_at)
        age_seconds = max(
            0,
            int((observed_now - observed_at).total_seconds()),
        )
        invocation_ref = f"model-invocation:{invocation.id}"
        evidence.append(
            ModelRoutePerformanceEvidence(
                provider=provider,
                model=invocation.model,
                succeeded=invocation.status == InvocationStatus.SUCCEEDED.value,
                age_seconds=age_seconds,
                evidence_key=invocation_ref,
                evidence_refs=tuple(
                    dict.fromkeys(
                        (
                            invocation_ref,
                            f"verification:{reason}",
                            *refs,
                        )
                    )
                ),
                verified=True,
            )
        )

    return tuple(evidence)
