"""add revoked access tokens

Revision ID: 0019_revoked_access_tokens
Revises: 0018_organization_invitations
"""

from alembic import op
import sqlalchemy as sa

revision = "0019_revoked_access_tokens"
down_revision = "0018_organization_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revoked_access_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_sha256", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_sha256", name="uq_revoked_access_tokens_token_sha256"),
    )
    op.create_index(
        "ix_revoked_access_tokens_user_id",
        "revoked_access_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_revoked_access_tokens_token_sha256",
        "revoked_access_tokens",
        ["token_sha256"],
        unique=True,
    )
    op.create_index(
        "ix_revoked_access_tokens_expires_at",
        "revoked_access_tokens",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_revoked_access_tokens_expires_at", table_name="revoked_access_tokens")
    op.drop_index("ix_revoked_access_tokens_token_sha256", table_name="revoked_access_tokens")
    op.drop_index("ix_revoked_access_tokens_user_id", table_name="revoked_access_tokens")
    op.drop_table("revoked_access_tokens")
