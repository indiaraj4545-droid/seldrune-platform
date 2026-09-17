"""add immutable agent configuration revisions

Revision ID: 0015_agent_configuration_revisions
Revises: 0014_agent_tool_grants
"""

from alembic import op
import sqlalchemy as sa

revision = "0015_agent_configuration_revisions"
down_revision = "0014_agent_tool_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_configuration_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("change_kind", sa.String(length=32), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "version",
            name="uq_agent_configuration_revision_version",
        ),
    )
    op.create_index(
        "ix_agent_configuration_revisions_organization_id",
        "agent_configuration_revisions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_configuration_revisions_agent_id",
        "agent_configuration_revisions",
        ["agent_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_configuration_revisions_agent_id",
        table_name="agent_configuration_revisions",
    )
    op.drop_index(
        "ix_agent_configuration_revisions_organization_id",
        table_name="agent_configuration_revisions",
    )
    op.drop_table("agent_configuration_revisions")
