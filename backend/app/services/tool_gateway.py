from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.core.tools import ApprovalMode, ToolRisk, ToolRunStatus, ToolStatus
from backend.app.models.tool_definition import ToolDefinition
from backend.app.models.tool_run import ToolRun
from backend.app.services.audit import record_audit


class ToolGatewayError(RuntimeError):
    pass


def _echo(payload: dict[str, Any]) -> dict[str, Any]:
    return {"echo": payload}


def _text_stats(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload.get("text", "")
    if not isinstance(text, str):
        raise ToolGatewayError("text must be a string")
    return {
        "characters": len(text),
        "words": len(text.split()),
        "lines": len(text.splitlines()) if text else 0,
    }


_INTERNAL_ACTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "echo": _echo,
    "text-stats": _text_stats,
}


def allowed_internal_actions() -> tuple[str, ...]:
    return tuple(sorted(_INTERNAL_ACTIONS))


def requires_approval(tool: ToolDefinition) -> bool:
    return (
        tool.approval_mode == ApprovalMode.ALWAYS.value
        or tool.risk_level == ToolRisk.HIGH.value
    )


def create_tool_run(
    session: Session,
    *,
    tool: ToolDefinition,
    organization_id: UUID,
    requested_by_user_id: UUID,
    input_data: dict[str, Any],
    task_id: UUID | None = None,
) -> ToolRun:
    if tool.organization_id != organization_id:
        raise ToolGatewayError("Tool does not belong to this organization")
    if tool.status != ToolStatus.ACTIVE.value:
        raise ToolGatewayError("Tool is disabled")
    if tool.provider != "internal":
        raise ToolGatewayError("Only internal tools are supported in v0.8")
    if tool.action_name not in _INTERNAL_ACTIONS:
        raise ToolGatewayError("Tool action is not allow-listed")

    status = (
        ToolRunStatus.PENDING_APPROVAL
        if requires_approval(tool)
        else ToolRunStatus.APPROVED
    )
    run = ToolRun(
        organization_id=organization_id,
        tool_id=tool.id,
        task_id=task_id,
        requested_by_user_id=requested_by_user_id,
        status=status.value,
        input_data=input_data,
    )
    session.add(run)
    session.flush()
    record_audit(
        session,
        organization_id=organization_id,
        actor_user_id=requested_by_user_id,
        action="tool.run.requested",
        resource_type="tool_run",
        resource_id=str(run.id),
        details={
            "tool_id": str(tool.id),
            "status": run.status,
            "risk_level": tool.risk_level,
        },
    )
    session.commit()
    session.refresh(run)
    return run


def execute_tool_run(
    session: Session,
    *,
    run: ToolRun,
    tool: ToolDefinition,
    actor_user_id: UUID,
) -> ToolRun:
    if run.status != ToolRunStatus.APPROVED.value:
        raise ToolGatewayError("Tool run is not approved for execution")
    action = _INTERNAL_ACTIONS.get(tool.action_name)
    if action is None:
        raise ToolGatewayError("Tool action is not allow-listed")

    run.status = ToolRunStatus.RUNNING.value
    run.started_at = datetime.now(UTC)
    session.commit()

    try:
        output = action(run.input_data)
    except ToolGatewayError as exc:
        run.status = ToolRunStatus.FAILED.value
        run.error_message = str(exc)
        run.completed_at = datetime.now(UTC)
        record_audit(
            session,
            organization_id=run.organization_id,
            actor_user_id=actor_user_id,
            action="tool.run.failed",
            resource_type="tool_run",
            resource_id=str(run.id),
            details={"tool_id": str(tool.id), "error": str(exc)},
        )
        session.commit()
        session.refresh(run)
        return run

    run.status = ToolRunStatus.SUCCEEDED.value
    run.output_data = output
    run.completed_at = datetime.now(UTC)
    record_audit(
        session,
        organization_id=run.organization_id,
        actor_user_id=actor_user_id,
        action="tool.run.succeeded",
        resource_type="tool_run",
        resource_id=str(run.id),
        details={"tool_id": str(tool.id), "action_name": tool.action_name},
    )
    session.commit()
    session.refresh(run)
    return run


def approve_tool_run(
    session: Session,
    *,
    run: ToolRun,
    actor_user_id: UUID,
) -> ToolRun:
    if run.status != ToolRunStatus.PENDING_APPROVAL.value:
        raise ToolGatewayError("Tool run is not awaiting approval")
    run.status = ToolRunStatus.APPROVED.value
    run.decided_by_user_id = actor_user_id
    run.decided_at = datetime.now(UTC)
    record_audit(
        session,
        organization_id=run.organization_id,
        actor_user_id=actor_user_id,
        action="tool.run.approved",
        resource_type="tool_run",
        resource_id=str(run.id),
        details={"tool_id": str(run.tool_id)},
    )
    session.commit()
    session.refresh(run)
    return run


def reject_tool_run(
    session: Session,
    *,
    run: ToolRun,
    actor_user_id: UUID,
    reason: str | None = None,
) -> ToolRun:
    if run.status != ToolRunStatus.PENDING_APPROVAL.value:
        raise ToolGatewayError("Tool run is not awaiting approval")
    run.status = ToolRunStatus.REJECTED.value
    run.decided_by_user_id = actor_user_id
    run.decided_at = datetime.now(UTC)
    run.completed_at = run.decided_at
    run.error_message = reason
    record_audit(
        session,
        organization_id=run.organization_id,
        actor_user_id=actor_user_id,
        action="tool.run.rejected",
        resource_type="tool_run",
        resource_id=str(run.id),
        details={"tool_id": str(run.tool_id), "reason": reason},
    )
    session.commit()
    session.refresh(run)
    return run
