from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from backend.app.api.dependencies import CurrentUserDep, SessionDep, require_org_permission
from backend.app.core.rbac import Permission
from backend.app.models.agent import Agent
from backend.app.models.agent_revision import AgentConfigurationRevision
from backend.app.models.membership import Membership
from backend.app.models.tool_definition import ToolDefinition
from backend.app.schemas.agent_revision import AgentConfigurationRevisionPublic
from backend.app.schemas.agent_task import AgentPublic
from backend.app.services.agent_revisions import (
    apply_configuration_snapshot,
    capture_agent_revision,
    configuration_matches,
    validate_runtime_config,
)
from backend.app.services.audit import record_audit

router = APIRouter(prefix="/organizations", tags=["agent-revisions"])

agents_run_dependency = require_org_permission(Permission.AGENTS_RUN)
agents_manage_dependency = require_org_permission(Permission.AGENTS_MANAGE)
AgentsRunDep = Annotated[Membership, Depends(agents_run_dependency)]
AgentsManageDep = Annotated[Membership, Depends(agents_manage_dependency)]


def _get_agent(session: SessionDep, organization_id: UUID, agent_id: UUID) -> Agent:
    agent = session.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.organization_id == organization_id,
        )
    )
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


def _validate_snapshot_tool_slugs(
    session: SessionDep,
    organization_id: UUID,
    snapshot: dict,
) -> None:
    slugs = snapshot.get("allowed_tool_slugs")
    if slugs is None:
        return
    if not isinstance(slugs, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Revision contains an invalid tool policy",
        )
    if not slugs:
        return
    existing = set(
        session.scalars(
            select(ToolDefinition.slug).where(
                ToolDefinition.organization_id == organization_id,
                ToolDefinition.slug.in_(slugs),
            )
        )
    )
    missing = sorted(set(slugs) - existing)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"unknown_tool_slugs": missing},
        )


@router.get(
    "/{organization_id}/agents/{agent_id}/revisions",
    response_model=list[AgentConfigurationRevisionPublic],
)
def list_agent_revisions(
    organization_id: UUID,
    agent_id: UUID,
    _membership: AgentsRunDep,
    session: SessionDep,
) -> list[AgentConfigurationRevision]:
    _get_agent(session, organization_id, agent_id)
    return list(
        session.scalars(
            select(AgentConfigurationRevision)
            .where(
                AgentConfigurationRevision.organization_id == organization_id,
                AgentConfigurationRevision.agent_id == agent_id,
            )
            .order_by(AgentConfigurationRevision.version.asc())
        )
    )


@router.post(
    "/{organization_id}/agents/{agent_id}/revisions/{revision_id}/restore",
    response_model=AgentPublic,
)
def restore_agent_revision(
    organization_id: UUID,
    agent_id: UUID,
    revision_id: UUID,
    _membership: AgentsManageDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> Agent:
    agent = _get_agent(session, organization_id, agent_id)
    revision = session.scalar(
        select(AgentConfigurationRevision).where(
            AgentConfigurationRevision.id == revision_id,
            AgentConfigurationRevision.organization_id == organization_id,
            AgentConfigurationRevision.agent_id == agent_id,
        )
    )
    if revision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found")

    snapshot = revision.snapshot
    try:
        validate_runtime_config(snapshot.get("runtime_config", {}))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    _validate_snapshot_tool_slugs(session, organization_id, snapshot)

    if configuration_matches(agent, snapshot):
        return agent

    try:
        capture_agent_revision(
            session,
            agent=agent,
            actor_user_id=current_user.id,
            change_kind="baseline",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Current agent configuration cannot be revisioned until runtime_config "
                "secret-like keys are removed"
            ),
        ) from exc

    from_version = agent.version
    apply_configuration_snapshot(agent, snapshot)
    agent.version += 1
    restored_revision = capture_agent_revision(
        session,
        agent=agent,
        actor_user_id=current_user.id,
        change_kind="restored",
    )
    record_audit(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="agent.revision_restored",
        resource_type="agent",
        resource_id=str(agent.id),
        details={
            "source_revision_id": str(revision.id),
            "source_version": revision.version,
            "from_version": from_version,
            "to_version": agent.version,
            "created_revision_id": str(restored_revision.id),
        },
    )
    session.commit()
    session.refresh(agent)
    return agent
