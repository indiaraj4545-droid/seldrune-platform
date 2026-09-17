from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditLogPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID | None
    actor_user_id: UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    details: dict[str, Any]
    occurred_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogPublic]
    limit: int
    offset: int
    returned: int
