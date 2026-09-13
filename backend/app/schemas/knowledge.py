from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.core.knowledge import KnowledgeKind, MemoryKind, MemoryScope


class KnowledgeCreate(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    content: str = Field(min_length=1, max_length=100_000)
    kind: KnowledgeKind = KnowledgeKind.DOCUMENT
    tags: list[str] = Field(default_factory=list, max_length=50)
    source_type: str = Field(default="internal", min_length=2, max_length=40)
    source_uri: str | None = Field(default=None, max_length=1000)
    source_label: str | None = Field(default=None, max_length=240)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    created_by_user_id: UUID | None
    title: str
    content: str
    kind: str
    tags: list[str]
    source_type: str
    source_uri: str | None
    source_label: str | None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class MemoryCreate(BaseModel):
    scope: MemoryScope = MemoryScope.ORGANIZATION
    kind: MemoryKind = MemoryKind.FACT
    key: str = Field(min_length=2, max_length=240)
    content: str = Field(min_length=1, max_length=50_000)
    agent_id: UUID | None = None
    task_id: UUID | None = None
    importance: int = Field(default=50, ge=0, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_scope_target(self) -> "MemoryCreate":
        if self.scope is MemoryScope.AGENT and self.agent_id is None:
            raise ValueError("agent_id is required for agent-scoped memory")
        if self.scope is MemoryScope.TASK and self.task_id is None:
            raise ValueError("task_id is required for task-scoped memory")
        return self


class MemoryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    agent_id: UUID | None
    task_id: UUID | None
    created_by_user_id: UUID | None
    scope: str
    kind: str
    key: str
    content: str
    importance: int
    metadata_json: dict[str, Any]
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RetrievalHit(BaseModel):
    ref: str
    source: str
    title: str
    excerpt: str
    score: int
    source_uri: str | None = None


class RetrievalResponse(BaseModel):
    query: str
    hits: list[RetrievalHit]
