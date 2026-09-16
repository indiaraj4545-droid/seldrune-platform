from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.governance_policy import GovernancePolicy
from backend.app.models.organization_kernel import (
    DepartmentDelegation,
    OrganizationGoal,
    OrganizationProject,
)
from backend.app.services.owner_dashboard import build_owner_dashboard


_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _action(
    severity: str,
    title: str,
    detail: str,
    source: str,
    *,
    resource_id: str | None = None,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "title": title,
        "detail": detail,
        "source": source,
        "resource_id": resource_id,
    }


def build_executive_brief(session: Session, organization_id: UUID) -> dict[str, Any]:
    dashboard = build_owner_dashboard(session, organization_id)
    goals = list(
        session.scalars(
            select(OrganizationGoal).where(
                OrganizationGoal.organization_id == organization_id
            )
        )
    )
    projects = list(
        session.scalars(
            select(OrganizationProject).where(
                OrganizationProject.organization_id == organization_id,
                OrganizationProject.status != "cancelled",
            )
        )
    )
    delegations = list(
        session.scalars(
            select(DepartmentDelegation).where(
                DepartmentDelegation.organization_id == organization_id
            )
        )
    )
    policy = session.get(GovernancePolicy, organization_id)

    incidents = dashboard["operational_incidents"]
    treasury = dashboard["treasury"]
    commands = dashboard["command_counts"]
    execution = dashboard["execution"]
    agents = dashboard["agent_performance"]

    blocked_projects = [project for project in projects if project.status == "blocked"]
    active_projects = [project for project in projects if project.status == "active"]
    open_goals = [goal for goal in goals if goal.status in {"planned", "active", "blocked"}]
    blocked_goals = [goal for goal in goals if goal.status == "blocked"]
    open_delegations = [
        item
        for item in delegations
        if item.status in {"proposed", "accepted", "in_progress"}
    ]

    priorities: list[dict[str, Any]] = []
    if incidents["critical"]:
        priorities.append(
            _action(
                "critical",
                "Resolve critical operational incidents",
                f"{incidents['critical']} critical incident(s) require owner attention.",
                "operational_incidents",
            )
        )
    if treasury["overcommitted"]:
        priorities.append(
            _action(
                "critical",
                "Reduce treasury overcommitment",
                "Committed project funds exceed the organization allocation.",
                "treasury",
            )
        )
    for project in blocked_projects[:3]:
        priorities.append(
            _action(
                "high",
                f"Unblock project: {project.name}",
                "Project delivery is blocked and requires an owner decision or recovery action.",
                "project",
                resource_id=str(project.id),
            )
        )
    if blocked_goals:
        priorities.append(
            _action(
                "high",
                "Review blocked organization goals",
                f"{len(blocked_goals)} goal(s) are currently blocked.",
                "goals",
            )
        )
    if commands["awaiting_approval"]:
        priorities.append(
            _action(
                "medium",
                "Review pending governed commands",
                f"{commands['awaiting_approval']} command(s) are awaiting owner approval.",
                "owner_commands",
            )
        )
    if treasury["allocated_budget_usd"] > 0 and treasury["utilization"] >= 0.9:
        priorities.append(
            _action(
                "medium",
                "Review treasury headroom",
                f"Committed funds are at {treasury['utilization']:.0%} of allocated budget.",
                "treasury",
            )
        )
    weak_agents = [
        item
        for item in agents["ranked_agents"]
        if item["completed_tasks"] >= 3
        and item["success_rate"] is not None
        and item["success_rate"] < 0.7
    ]
    if weak_agents:
        names = ", ".join(item["name"] for item in weak_agents[:3])
        priorities.append(
            _action(
                "medium",
                "Review low-reliability agent routes",
                f"Verified delivery evidence is weak for: {names}.",
                "agent_performance",
            )
        )
    if open_goals and not active_projects:
        priorities.append(
            _action(
                "medium",
                "Convert active goals into delivery projects",
                "The organization has open goals but no active project delivery.",
                "portfolio",
            )
        )
    if not open_goals:
        priorities.append(
            _action(
                "low",
                "Define a measurable organization goal",
                "No planned, active, or blocked organization goal is currently recorded.",
                "goals",
            )
        )

    priorities.sort(key=lambda item: _SEVERITY_ORDER[item["severity"]])

    health_score = 100
    health_score -= min(36, incidents["critical"] * 12)
    health_score -= min(16, incidents["warning"] * 4)
    health_score -= min(24, len(blocked_projects) * 8)
    health_score -= min(18, len(blocked_goals) * 6)
    if treasury["overcommitted"]:
        health_score -= 20
    elif treasury["allocated_budget_usd"] > 0 and treasury["utilization"] >= 0.9:
        health_score -= 8
    health_score -= min(15, execution["failed_steps"] * 3)
    health_score = max(0, min(100, health_score))
    posture = "stable" if health_score >= 80 else "watch" if health_score >= 60 else "intervention"

    governance = {
        "max_steps_per_command": policy.max_steps_per_command if policy else 25,
        "max_project_budget_usd": policy.max_project_budget_usd if policy else 100.0,
        "allow_autonomous_execution": policy.allow_autonomous_execution if policy else True,
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "health": {
            "score": health_score,
            "posture": posture,
            "critical_incidents": incidents["critical"],
            "warning_incidents": incidents["warning"],
            "blocked_projects": len(blocked_projects),
            "blocked_goals": len(blocked_goals),
        },
        "operating_snapshot": {
            "open_goals": len(open_goals),
            "active_projects": len(active_projects),
            "open_delegations": len(open_delegations),
            "commands_awaiting_approval": commands["awaiting_approval"],
            "succeeded_steps": execution["succeeded_steps"],
            "failed_steps": execution["failed_steps"],
            "active_agents": agents["active_agent_count"],
            "total_agents": agents["agent_count"],
        },
        "treasury": treasury,
        "governance": governance,
        "priorities": priorities[:8],
        "top_agents": agents["ranked_agents"][:5],
        "recent_incidents": incidents["recent"][:5],
    }
