"""add login failure throttle records

Revision ID: 0020_login_failures
Revises: 0019_revoked_access_tokens
"""

from alembic import op
import sqlalchemy as sa

revision = "0020_login_failures"
down_revision = "0019_revoked_access_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_failures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("throttle_key_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_login_failures_occurred_at",
        "login_failures",
        ["occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_login_failures_throttle_key_occurred_at",
        "login_failures",
        ["throttle_key_sha256", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_login_failures_throttle_key_occurred_at",
        table_name="login_failures",
    )
    op.drop_index("ix_login_failures_occurred_at", table_name="login_failures")
    op.drop_table("login_failures")
