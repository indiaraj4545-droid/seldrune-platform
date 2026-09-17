"""add task project attribution and unpriced project usage

Revision ID: 0025_task_project_attribution
Revises: 0024_mfa_recovery_codes
"""

from alembic import op
import sqlalchemy as sa

revision = "0025_task_project_attribution"
down_revision = "0024_mfa_recovery_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organization_projects",
        sa.Column(
            "unpriced_model_invocation_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column("tasks", sa.Column("project_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_tasks_project_id"), "tasks", ["project_id"], unique=False)
    op.create_foreign_key(
        "fk_tasks_project_id_organization_projects",
        "tasks",
        "organization_projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_tasks_project_id_organization_projects",
        "tasks",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_tasks_project_id"), table_name="tasks")
    op.drop_column("tasks", "project_id")
    op.drop_column("organization_projects", "unpriced_model_invocation_count")
