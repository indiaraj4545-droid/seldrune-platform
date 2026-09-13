"""add runtime references and live connector policy

Revision ID: 0009_live_connectors
Revises: 0008_research_connectors
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_live_connectors"
down_revision = "0008_research_connectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "secret_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("locator", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
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
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "slug", name="uq_secret_references_org_slug"),
    )
    op.create_index(
        "ix_secret_references_organization_id",
        "secret_references",
        ["organization_id"],
    )
    op.create_index("ix_secret_references_status", "secret_references", ["status"])

    with op.batch_alter_table("research_connectors") as batch:
        batch.add_column(sa.Column("secret_reference_id", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column("approval_mode", sa.String(length=32), server_default="never", nullable=False)
        )
        batch.add_column(
            sa.Column("max_requests_per_run", sa.Integer(), server_default="10", nullable=False)
        )
        batch.add_column(sa.Column("allowed_hosts", sa.JSON(), server_default="[]", nullable=False))
        batch.add_column(
            sa.Column("allowed_repositories", sa.JSON(), server_default="[]", nullable=False)
        )
        batch.add_column(sa.Column("is_live", sa.Boolean(), server_default=sa.false(), nullable=False))
        batch.create_foreign_key(
            "fk_research_connectors_secret_reference",
            "secret_references",
            ["secret_reference_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("research_connectors") as batch:
        batch.drop_constraint("fk_research_connectors_secret_reference", type_="foreignkey")
        batch.drop_column("is_live")
        batch.drop_column("allowed_repositories")
        batch.drop_column("allowed_hosts")
        batch.drop_column("max_requests_per_run")
        batch.drop_column("approval_mode")
        batch.drop_column("secret_reference_id")
    op.drop_index("ix_secret_references_status", table_name="secret_references")
    op.drop_index("ix_secret_references_organization_id", table_name="secret_references")
    op.drop_table("secret_references")
