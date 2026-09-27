"""add encrypted Zoho Mail connections and OAuth state

Revision ID: 0054_zoho_mail_connection
Revises: 0053_seldrune_mail
"""
from alembic import op
import sqlalchemy as sa


revision = "0054_zoho_mail_connection"
down_revision = "0053_seldrune_mail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "zoho_mail_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("mailbox_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("zoho_org_id", sa.String(length=64), nullable=False),
        sa.Column("account_email", sa.String(length=320), nullable=False),
        sa.Column("data_center", sa.String(length=16), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connected_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["connected_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["mailbox_id"], ["mailboxes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mailbox_id", name="uq_zoho_mail_connections_mailbox_id"),
    )
    op.create_index(
        "ix_zoho_mail_connections_organization_id",
        "zoho_mail_connections",
        ["organization_id"],
    )
    op.create_table(
        "zoho_mail_oauth_states",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("mailbox_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["mailbox_id"], ["mailboxes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state_hash"),
    )
    op.create_index(
        "ix_zoho_mail_oauth_states_organization_id",
        "zoho_mail_oauth_states",
        ["organization_id"],
    )
    op.create_index(
        "ix_zoho_mail_oauth_states_mailbox_id",
        "zoho_mail_oauth_states",
        ["mailbox_id"],
    )
    op.create_index(
        "ix_zoho_mail_oauth_states_user_id", "zoho_mail_oauth_states", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_zoho_mail_oauth_states_user_id", table_name="zoho_mail_oauth_states")
    op.drop_index("ix_zoho_mail_oauth_states_mailbox_id", table_name="zoho_mail_oauth_states")
    op.drop_index(
        "ix_zoho_mail_oauth_states_organization_id", table_name="zoho_mail_oauth_states"
    )
    op.drop_table("zoho_mail_oauth_states")
    op.drop_index(
        "ix_zoho_mail_connections_organization_id", table_name="zoho_mail_connections"
    )
    op.drop_table("zoho_mail_connections")
