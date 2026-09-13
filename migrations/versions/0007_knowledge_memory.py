"""add knowledge and memory layer

Revision ID: 0007_knowledge_memory
Revises: 0006_tool_gateway
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_knowledge_memory"
down_revision = "0006_tool_gateway"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_uri", sa.String(length=1000), nullable=True),
        sa.Column("source_label", sa.String(length=240), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
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
    )
    op.create_index(
        "ix_knowledge_entries_organization_id",
        "knowledge_entries",
        ["organization_id"],
    )
    op.create_index("ix_knowledge_entries_kind", "knowledge_entries", ["kind"])

    op.create_table(
        "memory_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=240), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_items_organization_id", "memory_items", ["organization_id"])
    op.create_index("ix_memory_items_agent_id", "memory_items", ["agent_id"])
    op.create_index("ix_memory_items_task_id", "memory_items", ["task_id"])
    op.create_index("ix_memory_items_scope", "memory_items", ["scope"])
    op.create_index("ix_memory_items_kind", "memory_items", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_memory_items_kind", table_name="memory_items")
    op.drop_index("ix_memory_items_scope", table_name="memory_items")
    op.drop_index("ix_memory_items_task_id", table_name="memory_items")
    op.drop_index("ix_memory_items_agent_id", table_name="memory_items")
    op.drop_index("ix_memory_items_organization_id", table_name="memory_items")
    op.drop_table("memory_items")
    op.drop_index("ix_knowledge_entries_kind", table_name="knowledge_entries")
    op.drop_index(
        "ix_knowledge_entries_organization_id",
        table_name="knowledge_entries",
    )
    op.drop_table("knowledge_entries")
