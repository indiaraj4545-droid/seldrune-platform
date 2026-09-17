"""add human approval checkpoints

Revision ID: 0016_orchestration_approvals
Revises: 0015_agent_configuration_revisions
"""

from alembic import op
import sqlalchemy as sa

revision = "0016_orchestration_approvals"
down_revision = "0015_agent_configuration_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orchestration_steps",
        sa.Column(
            "requires_approval",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_table(
        "orchestration_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("orchestration_run_id", sa.Uuid(), nullable=False),
        sa.Column("orchestration_step_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["orchestration_run_id"],
            ["orchestration_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["orchestration_step_id"],
            ["orchestration_steps.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "orchestration_step_id",
            name="uq_orchestration_approval_step",
        ),
    )
    op.create_index(
        "ix_orchestration_approvals_organization_id",
        "orchestration_approvals",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_orchestration_approvals_orchestration_run_id",
        "orchestration_approvals",
        ["orchestration_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_orchestration_approvals_status",
        "orchestration_approvals",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_orchestration_approvals_status",
        table_name="orchestration_approvals",
    )
    op.drop_index(
        "ix_orchestration_approvals_orchestration_run_id",
        table_name="orchestration_approvals",
    )
    op.drop_index(
        "ix_orchestration_approvals_organization_id",
        table_name="orchestration_approvals",
    )
    op.drop_table("orchestration_approvals")
    op.drop_column("orchestration_steps", "requires_approval")
