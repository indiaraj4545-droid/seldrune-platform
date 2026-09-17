"""add TOTP MFA state

Revision ID: 0023_totp_mfa
Revises: 0022_security_events
"""

from alembic import op
import sqlalchemy as sa

revision = "0023_totp_mfa"
down_revision = "0022_security_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "mfa_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("mfa_nonce", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "mfa_nonce")
    op.drop_column("users", "mfa_enabled")
