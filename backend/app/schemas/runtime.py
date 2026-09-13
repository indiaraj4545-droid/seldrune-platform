from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from backend.app.core.modeling import InvocationStatus, ModelProvider


class ModelInvocationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    task_id: UUID
    agent_id: UUID
    provider: ModelProvider
    model: str
    status: InvocationStatus
    provider_response_id: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None
    latency_ms: int | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
