"""add agent model policy and versioning

Revision ID: 0013_agent_model_policy
Revises: 0012_owner_push_subscriptions
"""

from alembic import op
import sqlalchemy as sa

revision = "0013_agent_model_policy"
down_revision = "0012_owner_push_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "agents",
        sa.Column("allowed_model_providers", sa.JSON(), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column("allowed_models", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "allowed_models")
    op.drop_column("agents", "allowed_model_providers")
    op.drop_column("agents", "version")
