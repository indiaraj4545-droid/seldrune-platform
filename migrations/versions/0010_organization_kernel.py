"""add organization kernel

Revision ID: 0010_organization_kernel
Revises: 0009_live_connectors
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_organization_kernel"
down_revision = "0009_live_connectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("owner_agent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("mission", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("budget_limit_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("resource_limit_units", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "slug", name="uq_departments_org_slug"),
    )
    op.create_index("ix_departments_organization_id", "departments", ["organization_id"])
    op.create_index("ix_departments_owner_agent_id", "departments", ["owner_agent_id"])

    op.create_table(
        "organization_goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("parent_goal_id", sa.Uuid(), nullable=True),
        sa.Column("owner_agent_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="planned"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("target_metric", sa.String(length=160), nullable=True),
        sa.Column("target_value", sa.Float(), nullable=True),
        sa.Column("current_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["parent_goal_id"], ["organization_goals.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["owner_agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organization_goals_organization_id", "organization_goals", ["organization_id"])
    op.create_index("ix_organization_goals_department_id", "organization_goals", ["department_id"])
    op.create_index("ix_organization_goals_owner_agent_id", "organization_goals", ["owner_agent_id"])

    op.create_table(
        "organization_projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("goal_id", sa.Uuid(), nullable=True),
        sa.Column("lead_agent_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="planned"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("budget_limit_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("budget_spent_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("resource_limit_units", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("resource_used_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["goal_id"], ["organization_goals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "slug", name="uq_org_projects_org_slug"),
    )
    op.create_index("ix_organization_projects_organization_id", "organization_projects", ["organization_id"])
    op.create_index("ix_organization_projects_department_id", "organization_projects", ["department_id"])
    op.create_index("ix_organization_projects_goal_id", "organization_projects", ["goal_id"])
    op.create_index("ix_organization_projects_lead_agent_id", "organization_projects", ["lead_agent_id"])

    op.create_table(
        "department_delegations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("source_department_id", sa.Uuid(), nullable=False),
        sa.Column("target_department_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("goal_id", sa.Uuid(), nullable=True),
        sa.Column("assigned_agent_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="proposed"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("requested_resource_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_department_id"], ["departments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_department_id"], ["departments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["organization_projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["goal_id"], ["organization_goals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_department_delegations_organization_id", "department_delegations", ["organization_id"])
    op.create_index("ix_department_delegations_source_department_id", "department_delegations", ["source_department_id"])
    op.create_index("ix_department_delegations_target_department_id", "department_delegations", ["target_department_id"])


def downgrade() -> None:
    op.drop_index("ix_department_delegations_target_department_id", table_name="department_delegations")
    op.drop_index("ix_department_delegations_source_department_id", table_name="department_delegations")
    op.drop_index("ix_department_delegations_organization_id", table_name="department_delegations")
    op.drop_table("department_delegations")
    op.drop_index("ix_organization_projects_lead_agent_id", table_name="organization_projects")
    op.drop_index("ix_organization_projects_goal_id", table_name="organization_projects")
    op.drop_index("ix_organization_projects_department_id", table_name="organization_projects")
    op.drop_index("ix_organization_projects_organization_id", table_name="organization_projects")
    op.drop_table("organization_projects")
    op.drop_index("ix_organization_goals_owner_agent_id", table_name="organization_goals")
    op.drop_index("ix_organization_goals_department_id", table_name="organization_goals")
    op.drop_index("ix_organization_goals_organization_id", table_name="organization_goals")
    op.drop_table("organization_goals")
    op.drop_index("ix_departments_owner_agent_id", table_name="departments")
    op.drop_index("ix_departments_organization_id", table_name="departments")
    op.drop_table("departments")
