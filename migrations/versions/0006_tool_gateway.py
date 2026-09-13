"""Add tool gateway tables.

Revision ID: 0006_tool_gateway
Revises: 0005_model_gateway_runtime
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_tool_gateway"
down_revision = "0005_model_gateway_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("action_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("risk_level", sa.String(32), nullable=False),
        sa.Column("approval_mode", sa.String(32), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.UniqueConstraint("organization_id", "slug", name="uq_tool_definitions_org_slug"),
    )
    op.create_table(
        "tool_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("tool_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=False),
        sa.Column("output_data", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["tool_id"], ["tool_definitions.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"]),
    )
    op.create_index("ix_tool_definitions_organization_id", "tool_definitions", ["organization_id"])
    op.create_index("ix_tool_runs_organization_id", "tool_runs", ["organization_id"])
    op.create_index("ix_tool_runs_tool_id", "tool_runs", ["tool_id"])
    op.create_index("ix_tool_runs_status", "tool_runs", ["status"])


def downgrade() -> None:
    op.drop_table("tool_runs")
    op.drop_table("tool_definitions")
