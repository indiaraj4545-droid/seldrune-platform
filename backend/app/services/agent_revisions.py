from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.agent import Agent
from backend.app.models.agent_revision import AgentConfigurationRevision
from backend.app.services.audit import record_audit

_SECRET_KEY_MARKERS = (
    "secret",
    "token",
    "password",
    "api_key",
    "authorization",
    "credential",
    "private_key",
)


def _normalized_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _is_secret_like_key(value: str) -> bool:
    key = _normalized_key(value)
    return any(
        key == marker
        or key.startswith(f"{marker}_")
        or key.endswith(f"_{marker}")
        for marker in _SECRET_KEY_MARKERS
    )


def runtime_config_secret_paths(value: Any, path: str = "runtime_config") -> list[str]:
    matches: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if _is_secret_like_key(str(key)):
                matches.append(child_path)
            matches.extend(runtime_config_secret_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            matches.extend(runtime_config_secret_paths(child, f"{path}[{index}]"))
    return matches


def validate_runtime_config(runtime_config: dict[str, Any]) -> None:
    matches = runtime_config_secret_paths(runtime_config)
    if matches:
        raise ValueError(
            "runtime_config contains secret-like keys: " + ", ".join(sorted(set(matches)))
        )


def configuration_snapshot(agent: Agent) -> dict[str, Any]:
    return deepcopy(
        {
            "name": agent.name,
            "description": agent.description,
            "capabilities": agent.capabilities,
            "runtime_config": agent.runtime_config,
            "allowed_model_providers": agent.allowed_model_providers,
            "allowed_models": agent.allowed_models,
            "allowed_tool_slugs": agent.allowed_tool_slugs,
        }
    )


def configuration_matches(agent: Agent, snapshot: dict[str, Any]) -> bool:
    return configuration_snapshot(agent) == snapshot


def capture_snapshot_revision(
    session: Session,
    *,
    agent: Agent,
    version: int,
    snapshot: dict[str, Any],
    actor_user_id: UUID | None,
    change_kind: str,
) -> AgentConfigurationRevision:
    validate_runtime_config(snapshot.get("runtime_config", {}))
    existing = session.scalar(
        select(AgentConfigurationRevision).where(
            AgentConfigurationRevision.agent_id == agent.id,
            AgentConfigurationRevision.version == version,
        )
    )
    if existing is not None:
        return existing

    revision = AgentConfigurationRevision(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        version=version,
        change_kind=change_kind,
        snapshot=deepcopy(snapshot),
        created_by_user_id=actor_user_id,
    )
    session.add(revision)
    session.flush()
    record_audit(
        session,
        organization_id=agent.organization_id,
        actor_user_id=actor_user_id,
        action="agent.revision_created",
        resource_type="agent_revision",
        resource_id=str(revision.id),
        details={
            "agent_id": str(agent.id),
            "version": version,
            "change_kind": change_kind,
        },
    )
    return revision


def capture_agent_revision(
    session: Session,
    *,
    agent: Agent,
    actor_user_id: UUID | None,
    change_kind: str,
) -> AgentConfigurationRevision:
    return capture_snapshot_revision(
        session,
        agent=agent,
        version=agent.version,
        snapshot=configuration_snapshot(agent),
        actor_user_id=actor_user_id,
        change_kind=change_kind,
    )


def apply_configuration_snapshot(agent: Agent, snapshot: dict[str, Any]) -> None:
    agent.name = snapshot["name"]
    agent.description = snapshot.get("description")
    agent.capabilities = deepcopy(snapshot.get("capabilities", []))
    agent.runtime_config = deepcopy(snapshot.get("runtime_config", {}))
    agent.allowed_model_providers = deepcopy(snapshot.get("allowed_model_providers"))
    agent.allowed_models = deepcopy(snapshot.get("allowed_models"))
    agent.allowed_tool_slugs = deepcopy(snapshot.get("allowed_tool_slugs"))
