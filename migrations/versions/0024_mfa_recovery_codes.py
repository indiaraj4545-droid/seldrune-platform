"""add MFA recovery codes

Revision ID: 0024_mfa_recovery_codes
Revises: 0023_totp_mfa
"""

from alembic import op
import sqlalchemy as sa

revision = "0024_mfa_recovery_codes"
down_revision = "0023_totp_mfa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mfa_recovery_codes_user_id"),
        "mfa_recovery_codes",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mfa_recovery_codes_code_digest"),
        "mfa_recovery_codes",
        ["code_digest"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mfa_recovery_codes_code_digest"), table_name="mfa_recovery_codes")
    op.drop_index(op.f("ix_mfa_recovery_codes_user_id"), table_name="mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
