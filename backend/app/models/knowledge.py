from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="internal")
    source_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_label: Mapped[str | None] = mapped_column(String(240), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
