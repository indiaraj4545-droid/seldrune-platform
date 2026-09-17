from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class AgentConfigurationRevision(Base):
    __tablename__ = "agent_configuration_revisions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_configuration_revision_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    change_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
