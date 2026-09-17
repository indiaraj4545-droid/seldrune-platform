from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BillingInvocationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    agent_id: UUID
    provider: str
    model: str
    status: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None
    latency_ms: int | None
    created_at: datetime
    completed_at: datetime | None


class BillingInvocationPage(BaseModel):
    items: list[BillingInvocationPublic]
    limit: int
    offset: int
    returned: int


class BillingUsageTotals(BaseModel):
    invocation_count: int
    succeeded_count: int
    failed_count: int
    running_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    priced_invocation_count: int
    unpriced_invocation_count: int
    known_estimated_cost_usd: float
    average_latency_ms: float | None


class BillingUsageBreakdown(BaseModel):
    provider: str
    model: str
    invocation_count: int
    total_tokens: int
    priced_invocation_count: int
    unpriced_invocation_count: int
    known_estimated_cost_usd: float


class BillingProjectUsageBreakdown(BaseModel):
    project_id: UUID | None
    department_id: UUID | None
    invocation_count: int
    total_tokens: int
    priced_invocation_count: int
    unpriced_invocation_count: int
    known_estimated_cost_usd: float


class BillingDepartmentUsageBreakdown(BaseModel):
    department_id: UUID | None
    invocation_count: int
    total_tokens: int
    priced_invocation_count: int
    unpriced_invocation_count: int
    known_estimated_cost_usd: float


class BillingUsageSummary(BaseModel):
    totals: BillingUsageTotals
    by_provider_model: list[BillingUsageBreakdown]
    by_project: list[BillingProjectUsageBreakdown]
    by_department: list[BillingDepartmentUsageBreakdown]


class ProjectAccountingCorrection(BaseModel):
    budget_spent_usd: float | None = Field(default=None, ge=0)
    unpriced_model_invocation_count: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def require_change(self) -> "ProjectAccountingCorrection":
        if self.budget_spent_usd is None and self.unpriced_model_invocation_count is None:
            raise ValueError("Provide a spend or unresolved-count correction")
        return self
