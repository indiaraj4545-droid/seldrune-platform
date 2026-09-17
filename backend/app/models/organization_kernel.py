from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_departments_org_slug"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    owner_agent_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    mission: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    budget_limit_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    resource_limit_units: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OrganizationGoal(Base):
    __tablename__ = "organization_goals"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    department_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parent_goal_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("organization_goals.id", ondelete="SET NULL"), nullable=True
    )
    owner_agent_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    target_metric: Mapped[str | None] = mapped_column(String(160), nullable=True)
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OrganizationProject(Base):
    __tablename__ = "organization_projects"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_org_projects_org_slug"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    department_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    goal_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("organization_goals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lead_agent_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    budget_limit_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    budget_spent_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unpriced_model_invocation_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    resource_limit_units: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    resource_used_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DepartmentDelegation(Base):
    __tablename__ = "department_delegations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_department_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_department_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("organization_projects.id", ondelete="SET NULL"), nullable=True
    )
    goal_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("organization_goals.id", ondelete="SET NULL"), nullable=True
    )
    assigned_agent_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    requested_resource_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
