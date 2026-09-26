from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.models.task import Task
from backend.app.models.tool_run import ToolRun
from backend.app.services.cognitive_evidence import verify_task_completion_evidence
from backend.app.services.unarchi_engine import UnarchiEngine, VerifiedToolOutcome


class UnarchiToolFeedbackError(RuntimeError):
    pass


def _bounded_output_summary(value: object, *, limit: int = 2000) -> str:
    try:
        rendered = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as exc:
        raise UnarchiToolFeedbackError(
            "verified tool output is not JSON serializable"
        ) from exc
    if len(rendered) <= limit:
        return rendered
    return rendered[: limit - 14] + "...[truncated]"


def feed_verified_tool_task(
    session: Session,
    *,
    engine: UnarchiEngine,
    task: Task,
    predicted_success: float = 0.5,
) -> VerifiedToolOutcome:
    """
    Feed a governed tool task into UNARCHI only after repository evidence verifies it.

    The adapter is read-only with respect to the tool gateway: it does not create,
    approve, execute, retry, or mutate a ToolRun.
    """
    valid, reason, refs = verify_task_completion_evidence(
        session,
        task=task,
    )
    if not valid or reason != "verified_tool_receipt":
        raise UnarchiToolFeedbackError(
            f"tool outcome rejected by evidence gate: {reason}"
        )

    output = task.output_data or {}
    if not isinstance(output, dict) or output.get("execution_type") != "tool":
        raise UnarchiToolFeedbackError("verified task has no tool execution output")

    evidence = output.get("evidence")
    if not isinstance(evidence, dict):
        raise UnarchiToolFeedbackError("verified task has no tool evidence")

    try:
        tool_run_id = UUID(str(evidence.get("tool_run_id") or ""))
    except (TypeError, ValueError) as exc:
        raise UnarchiToolFeedbackError("invalid verified tool run id") from exc

    run = session.get(ToolRun, tool_run_id)
    if run is None:
        raise UnarchiToolFeedbackError("verified tool run disappeared")

    tool_slug = str(output.get("tool_slug") or "").strip()
    receipt_id = str(evidence.get("receipt_id") or "").strip()
    if not tool_slug or not receipt_id:
        raise UnarchiToolFeedbackError("verified tool identity is incomplete")

    summary = _bounded_output_summary(run.output_data or {})
    goal = (task.objective or task.title or "consume verified tool outcome").strip()

    return engine.ingest_verified_tool_outcome(
        tool_slug=tool_slug,
        receipt_id=receipt_id,
        tool_run_id=str(run.id),
        goal=goal,
        output_summary=summary,
        verification_reason=reason,
        source_refs=tuple(refs),
        execution_succeeded=True,
        predicted_success=predicted_success,
    )
