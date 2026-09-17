"""add agent tool grants and tool-run agent traceability

Revision ID: 0014_agent_tool_grants
Revises: 0013_agent_model_policy
"""

from alembic import op
import sqlalchemy as sa

revision = "0014_agent_tool_grants"
down_revision = "0013_agent_model_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("allowed_tool_slugs", sa.JSON(), nullable=True),
    )
    op.add_column(
        "tool_runs",
        sa.Column("agent_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tool_runs_agent_id_agents",
        "tool_runs",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_tool_runs_agent_id",
        "tool_runs",
        ["agent_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tool_runs_agent_id", table_name="tool_runs")
    op.drop_constraint(
        "fk_tool_runs_agent_id_agents",
        "tool_runs",
        type_="foreignkey",
    )
    op.drop_column("tool_runs", "agent_id")
    op.drop_column("agents", "allowed_tool_slugs")
