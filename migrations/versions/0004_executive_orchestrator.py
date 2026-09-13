"""add executive orchestrator

Revision ID: 0004_executive_orchestrator
Revises: 0003_agent_task_engine
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_executive_orchestrator"
down_revision = "0003_agent_task_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orchestration_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("planner_version", sa.String(length=64), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_orchestration_runs_organization_id", "orchestration_runs", ["organization_id"]
    )
    op.create_index("ix_orchestration_runs_status", "orchestration_runs", ["status"])

    op.create_table(
        "orchestration_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("orchestration_run_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_agent_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("required_capabilities", sa.JSON(), nullable=False),
        sa.Column("match_score", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["assigned_agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["orchestration_run_id"], ["orchestration_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index(
        "ix_orchestration_steps_orchestration_run_id",
        "orchestration_steps",
        ["orchestration_run_id"],
    )
    op.create_index(
        "ix_orchestration_steps_organization_id", "orchestration_steps", ["organization_id"]
    )
    op.create_index(
        "ix_orchestration_steps_assigned_agent_id", "orchestration_steps", ["assigned_agent_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_orchestration_steps_assigned_agent_id", table_name="orchestration_steps")
    op.drop_index("ix_orchestration_steps_organization_id", table_name="orchestration_steps")
    op.drop_index("ix_orchestration_steps_orchestration_run_id", table_name="orchestration_steps")
    op.drop_table("orchestration_steps")
    op.drop_index("ix_orchestration_runs_status", table_name="orchestration_runs")
    op.drop_index("ix_orchestration_runs_organization_id", table_name="orchestration_runs")
    op.drop_table("orchestration_runs")
