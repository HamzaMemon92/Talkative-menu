"""customer ai conversations

Revision ID: 014_customer_ai_conversations
Revises: 013_billing_tax_invoice
Create Date: 2026-09-10 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "014_customer_ai_conversations"
down_revision: str | None = "013_billing_tax_invoice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dining_session_id", sa.Uuid(), nullable=False),
        sa.Column("outlet_id", sa.Uuid(), nullable=False),
        sa.Column("public_token", sa.String(length=96), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "closed", name="ai_conversation_status", native_enum=False),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["dining_session_id"], ["dining_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["outlet_id"], ["restaurant_outlets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_ai_conversations_public_token", "ai_conversations", ["public_token"], unique=True
    )
    op.create_index("ix_ai_conversations_session", "ai_conversations", ["dining_session_id"])

    op.create_table(
        "ai_conversation_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("client_message_id", sa.String(length=120), nullable=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", name="ai_message_role", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "processing",
                "completed",
                "pending_confirmation",
                "failed",
                name="ai_message_status",
                native_enum=False,
            ),
            server_default="completed",
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("sequence_number >= 1", name="ck_ai_message_sequence"),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "client_message_id", name="uq_ai_message_client_id"),
        sa.UniqueConstraint("conversation_id", "sequence_number", name="uq_ai_message_sequence"),
    )
    op.create_index(
        "ix_ai_messages_conversation_sequence",
        "ai_conversation_messages",
        ["conversation_id", "sequence_number"],
    )

    op.create_table(
        "ai_pending_tool_confirmations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_confirmation_token", sa.String(length=96), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=True),
        sa.Column("tool_name", sa.String(length=120), nullable=False),
        sa.Column("validated_arguments_json", sa.JSON(), nullable=False),
        sa.Column("confirmation_summary_json", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "confirmed",
                "cancelled",
                "expired",
                name="ai_pending_confirmation_status",
                native_enum=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_message_id"], ["ai_conversation_messages.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_ai_pending_confirmation_token",
        "ai_pending_tool_confirmations",
        ["public_confirmation_token"],
        unique=True,
    )
    op.create_index(
        "ix_ai_pending_confirmation_conversation",
        "ai_pending_tool_confirmations",
        ["conversation_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_pending_confirmation_conversation",
        table_name="ai_pending_tool_confirmations",
    )
    op.drop_index("uq_ai_pending_confirmation_token", table_name="ai_pending_tool_confirmations")
    op.drop_table("ai_pending_tool_confirmations")
    op.drop_index("ix_ai_messages_conversation_sequence", table_name="ai_conversation_messages")
    op.drop_table("ai_conversation_messages")
    op.drop_index("ix_ai_conversations_session", table_name="ai_conversations")
    op.drop_index("uq_ai_conversations_public_token", table_name="ai_conversations")
    op.drop_table("ai_conversations")
