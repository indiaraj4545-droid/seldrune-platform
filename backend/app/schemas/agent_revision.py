from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AgentConfigurationRevisionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    agent_id: UUID
    version: int
    change_kind: str
    snapshot: dict[str, Any]
    created_by_user_id: UUID | None
    created_at: datetime
