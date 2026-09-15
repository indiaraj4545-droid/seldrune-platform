from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.app.core.config import settings
from backend.app.models.organization_kernel import OrganizationProject
from backend.app.models.orchestration import OrchestrationRun


class PortfolioGovernorError(RuntimeError):
    pass


def _budget_reservations(project: OrganizationProject | None) -> list[dict[str, Any]]:
    if project is None:
        return []
    reservations = (project.metadata_json or {}).get("budget_reservations") or []
    return [item for item in reservations if isinstance(item, dict)]


def reserved_project_budget(
    project: OrganizationProject | None,
    *,
    exclude_command_id: str | None = None,
) -> float:
    return round(
        sum(
            float(item.get("amount_usd", 0))
            for item in _budget_reservations(project)
            if item.get("status") == "active"
            and item.get("command_id") != exclude_command_id
        ),
        8,
    )


def reserve_project_budget(
    *,
    project: OrganizationProject,
    run: OrchestrationRun,
    amount_usd: float,
    actor_user_id: str,
) -> dict[str, Any]:
    command_id = str(run.id)
    reservations = _budget_reservations(project)
    existing = next(
        (
            item
            for item in reservations
            if item.get("command_id") == command_id and item.get("status") == "active"
        ),
        None,
    )
    if existing is not None:
        return existing

    reservation = {
        "command_id": command_id,
        "amount_usd": round(max(amount_usd, 0), 8),
        "status": "active",
        "reserved_at": datetime.now(UTC).isoformat(),
        "reserved_by": actor_user_id,
    }
    project.metadata_json = {
        **(project.metadata_json or {}),
        "budget_reservations": [*reservations, reservation],
    }
    return reservation


def release_project_budget(
    *,
    project: OrganizationProject,
    command_id: str,
    actual_cost_usd: float,
) -> dict[str, Any] | None:
    reservations = _budget_reservations(project)
    released: dict[str, Any] | None = None
    updated: list[dict[str, Any]] = []
    for item in reservations:
        if item.get("command_id") == command_id and item.get("status") == "active":
            item = {
                **item,
                "status": "reconciled",
                "released_at": datetime.now(UTC).isoformat(),
                "actual_cost_usd": round(max(actual_cost_usd, 0), 8),
                "variance_usd": round(
                    float(item.get("amount_usd", 0)) - max(actual_cost_usd, 0),
                    8,
                ),
            }
            released = item
        updated.append(item)
    if released is not None:
        project.metadata_json = {
            **(project.metadata_json or {}),
            "budget_reservations": updated,
        }
    return released



def revoke_project_budget_reservation(
    *,
    project: OrganizationProject,
    command_id: str,
    actor_user_id: str,
    reason: str = "owner_revoked_approval",
) -> dict[str, Any] | None:
    reservations = _budget_reservations(project)
    released: dict[str, Any] | None = None
    updated: list[dict[str, Any]] = []
    for item in reservations:
        if item.get("command_id") == command_id and item.get("status") == "active":
            item = {
                **item,
                "status": "released",
                "released_at": datetime.now(UTC).isoformat(),
                "released_by": actor_user_id,
                "release_reason": reason,
            }
            released = item
        updated.append(item)
    if released is not None:
        project.metadata_json = {
            **(project.metadata_json or {}),
            "budget_reservations": updated,
        }
    return released


def evaluate_project_execution(
    *,
    project: OrganizationProject | None,
    run: OrchestrationRun,
    delivery_context: dict[str, Any],
) -> dict[str, Any]:
    required_units = max(
        int((run.summary or {}).get("step_count", 0))
        - int((run.summary or {}).get("succeeded_steps", 0)),
        0,
    )
    resource_limit = (
        project.resource_limit_units
        if project is not None
        else int(delivery_context.get("resource_limit_units", 0))
    )
    resource_used = (
        project.resource_used_units
        if project is not None
        else int(delivery_context.get("resource_used_units", 0))
    )
    budget_limit = (
        project.budget_limit_usd
        if project is not None
        else float(delivery_context.get("budget_limit_usd", 0))
    )
    budget_spent = (
        project.budget_spent_usd
        if project is not None
        else float(delivery_context.get("budget_spent_usd", 0))
    )
    reserved_budget = reserved_project_budget(
        project,
        exclude_command_id=str(run.id),
    )
    remaining_units = max(resource_limit - resource_used, 0)
    budget_configured = budget_limit > 0
    remaining_budget = (
        round(max(budget_limit - budget_spent - reserved_budget, 0), 8)
        if budget_configured
        else None
    )
    estimated_cost = round(
        required_units * settings.project_estimated_cost_per_step_usd,
        8,
    )
    reasons: list[str] = []
    if required_units > remaining_units:
        reasons.append(
            f"Plan requires {required_units} capacity units but only {remaining_units} remain"
        )
    if budget_configured and budget_spent + reserved_budget >= budget_limit:
        reasons.append("Project budget is exhausted or reserved")
    elif budget_configured and estimated_cost > (remaining_budget or 0):
        reasons.append(
            f"Forecast cost USD {estimated_cost:.2f} exceeds remaining budget "
            f"USD {(remaining_budget or 0):.2f}"
        )

    decision = {
        "allowed": not reasons,
        "project_id": delivery_context.get("project_id"),
        "command_id": str(run.id),
        "required_resource_units": required_units,
        "remaining_resource_units": remaining_units,
        "budget_limit_configured": budget_configured,
        "budget_reserved_usd": reserved_budget,
        "remaining_budget_usd": remaining_budget,
        "estimated_cost_per_step_usd": settings.project_estimated_cost_per_step_usd,
        "estimated_execution_cost_usd": estimated_cost,
        "projected_budget_spent_usd": round(
            budget_spent + reserved_budget + estimated_cost,
            8,
        ),
        "reasons": reasons,
    }
    return decision
