from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SecurityEventPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    event_type: str
    severity: str
    status: str
    actor_user_id: UUID | None
    resource_type: str
    resource_id: str | None
    details: dict[str, Any]
    occurred_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by_user_id: UUID | None


class SecurityEventPage(BaseModel):
    items: list[SecurityEventPublic]
    total: int
    limit: int
    offset: int
