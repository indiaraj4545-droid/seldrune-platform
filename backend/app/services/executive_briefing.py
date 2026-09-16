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


def _command_action(label: str, objective: str) -> dict[str, str]:
    return {"kind": "owner_command", "label": label, "objective": objective}


def _navigate_action(label: str, href: str) -> dict[str, str]:
    return {"kind": "navigate", "label": label, "href": href}


def _action(
    key: str,
    severity: str,
    title: str,
    detail: str,
    source: str,
    *,
    resource_id: str | None = None,
    action: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "severity": severity,
        "title": title,
        "detail": detail,
        "source": source,
        "resource_id": resource_id,
        "action": action,
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
                "critical-incidents",
                "critical",
                "Resolve critical operational incidents",
                f"{incidents['critical']} critical incident(s) require owner attention.",
                "operational_incidents",
                action=_command_action(
                    "Create incident recovery command",
                    "Review the current critical operational incidents, identify root causes, "
                    "produce a governed recovery plan, and define evidence required to verify "
                    "that each incident is resolved.",
                ),
            )
        )
    if treasury["overcommitted"]:
        priorities.append(
            _action(
                "treasury-overcommitment",
                "critical",
                "Reduce treasury overcommitment",
                "Committed project funds exceed the organization allocation.",
                "treasury",
                action=_command_action(
                    "Create treasury recovery command",
                    "Analyze the current organization treasury overcommitment and produce a "
                    "governed plan to restore budget headroom without bypassing active project "
                    "controls or existing owner approvals.",
                ),
            )
        )
    for project in blocked_projects[:3]:
        priorities.append(
            _action(
                f"blocked-project:{project.id}",
                "high",
                f"Unblock project: {project.name}",
                "Project delivery is blocked and requires an owner decision or recovery action.",
                "project",
                resource_id=str(project.id),
                action=_command_action(
                    "Create project recovery command",
                    f"Diagnose why the project '{project.name}' is blocked, preserve its "
                    "governance and resource limits, propose the smallest safe recovery plan, "
                    "and define acceptance evidence before resuming delivery.",
                ),
            )
        )
    if blocked_goals:
        priorities.append(
            _action(
                "blocked-goals",
                "high",
                "Review blocked organization goals",
                f"{len(blocked_goals)} goal(s) are currently blocked.",
                "goals",
                action=_command_action(
                    "Create goal recovery command",
                    "Review the blocked organization goals, identify shared dependencies and "
                    "constraints, and produce a governed recovery sequence with measurable "
                    "completion evidence.",
                ),
            )
        )
    if commands["awaiting_approval"]:
        priorities.append(
            _action(
                "pending-approvals",
                "medium",
                "Review pending governed commands",
                f"{commands['awaiting_approval']} command(s) are awaiting owner approval.",
                "owner_commands",
                action=_navigate_action("Open Owner Console", "/console"),
            )
        )
    if treasury["allocated_budget_usd"] > 0 and treasury["utilization"] >= 0.9:
        priorities.append(
            _action(
                "treasury-headroom",
                "medium",
                "Review treasury headroom",
                f"Committed funds are at {treasury['utilization']:.0%} of allocated budget.",
                "treasury",
                action=_command_action(
                    "Create budget review command",
                    "Review current treasury utilization and active project commitments, then "
                    "produce options for preserving delivery while increasing safe budget "
                    "headroom under existing governance policy.",
                ),
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
                "weak-agent-routes",
                "medium",
                "Review low-reliability agent routes",
                f"Verified delivery evidence is weak for: {names}.",
                "agent_performance",
                action=_command_action(
                    "Create routing improvement command",
                    f"Analyze verified delivery evidence for these lower-reliability agent "
                    f"routes: {names}. Propose governed routing or capability improvements and "
                    "define how improvement will be measured before changing production routing.",
                ),
            )
        )
    if open_goals and not active_projects:
        priorities.append(
            _action(
                "goals-without-delivery",
                "medium",
                "Convert active goals into delivery projects",
                "The organization has open goals but no active project delivery.",
                "portfolio",
                action=_command_action(
                    "Create delivery portfolio command",
                    "Review the organization's open goals and propose the smallest set of "
                    "governed delivery projects needed to make measurable progress, including "
                    "resource and budget assumptions for owner review.",
                ),
            )
        )
    if not open_goals:
        priorities.append(
            _action(
                "no-open-goals",
                "low",
                "Define a measurable organization goal",
                "No planned, active, or blocked organization goal is currently recorded.",
                "goals",
                action=_navigate_action(
                    "Open Organization Board", "/console-assets/organization-board.html"
                ),
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
    posture = (
        "stable"
        if health_score >= 80
        else "watch"
        if health_score >= 60
        else "intervention"
    )

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
