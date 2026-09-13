from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class MemoryItem(Base):
    __tablename__ = "memory_items"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    task_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
