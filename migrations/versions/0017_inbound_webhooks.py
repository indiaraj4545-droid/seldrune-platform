"""add signed inbound webhook gateway

Revision ID: 0017_inbound_webhooks
Revises: 0016_orchestration_approvals
"""

from alembic import op
import sqlalchemy as sa

revision = "0017_inbound_webhooks"
down_revision = "0016_orchestration_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("secret_reference_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("allowed_event_types", sa.JSON(), nullable=False),
        sa.Column("max_payload_bytes", sa.Integer(), server_default="65536", nullable=False),
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
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["secret_reference_id"],
            ["secret_references.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "slug",
            name="uq_webhook_endpoints_org_slug",
        ),
    )
    op.create_index(
        "ix_webhook_endpoints_organization_id",
        "webhook_endpoints",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_webhook_endpoints_secret_reference_id",
        "webhook_endpoints",
        ["secret_reference_id"],
        unique=False,
    )
    op.create_index(
        "ix_webhook_endpoints_status",
        "webhook_endpoints",
        ["status"],
        unique=False,
    )

    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["webhook_endpoints.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "endpoint_id",
            "delivery_id",
            name="uq_webhook_events_endpoint_delivery",
        ),
    )
    op.create_index(
        "ix_webhook_events_organization_id",
        "webhook_events",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_webhook_events_endpoint_id",
        "webhook_events",
        ["endpoint_id"],
        unique=False,
    )
    op.create_index(
        "ix_webhook_events_event_type",
        "webhook_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_webhook_events_received_at",
        "webhook_events",
        ["received_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_events_received_at", table_name="webhook_events")
    op.drop_index("ix_webhook_events_event_type", table_name="webhook_events")
    op.drop_index("ix_webhook_events_endpoint_id", table_name="webhook_events")
    op.drop_index("ix_webhook_events_organization_id", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_index("ix_webhook_endpoints_status", table_name="webhook_endpoints")
    op.drop_index("ix_webhook_endpoints_secret_reference_id", table_name="webhook_endpoints")
    op.drop_index("ix_webhook_endpoints_organization_id", table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")
