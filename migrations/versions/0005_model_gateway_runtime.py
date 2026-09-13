"""add model gateway runtime

Revision ID: 0005_model_gateway_runtime
Revises: 0004_executive_orchestrator
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_model_gateway_runtime"
down_revision = "0004_executive_orchestrator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_response_id", sa.String(length=255), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_invocations_organization_id",
        "model_invocations",
        ["organization_id"],
    )
    op.create_index("ix_model_invocations_task_id", "model_invocations", ["task_id"])
    op.create_index("ix_model_invocations_agent_id", "model_invocations", ["agent_id"])
    op.create_index("ix_model_invocations_provider", "model_invocations", ["provider"])
    op.create_index("ix_model_invocations_status", "model_invocations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_model_invocations_status", table_name="model_invocations")
    op.drop_index("ix_model_invocations_provider", table_name="model_invocations")
    op.drop_index("ix_model_invocations_agent_id", table_name="model_invocations")
    op.drop_index("ix_model_invocations_task_id", table_name="model_invocations")
    op.drop_index(
        "ix_model_invocations_organization_id",
        table_name="model_invocations",
    )
    op.drop_table("model_invocations")
