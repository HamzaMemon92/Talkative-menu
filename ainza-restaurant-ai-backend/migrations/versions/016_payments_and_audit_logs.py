"""payments and audit logs

Revision ID: 016_payments_and_audit
Revises: 015_pending_reco
Create Date: 2026-09-14 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "016_payments_and_audit"
down_revision: str | None = "015_pending_reco"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── payment_intents ────────────────────────────────────────────────────────
    op.create_table(
        "payment_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outlet_id", sa.Uuid(), nullable=False),
        sa.Column("dining_session_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "success", "failed", "cancelled", "expired", name="payment_intent_status", native_enum=False),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "payment_mode",
            sa.Enum("online", "pay_at_table", "pay_at_counter", name="payment_intent_mode", native_enum=False),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=50), server_default="fake", nullable=False),
        sa.Column("provider_intent_reference", sa.String(length=120), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("qr_payload", sa.Text(), nullable=True),
        sa.Column("checkout_url", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_payment_intents_amount"),
        sa.ForeignKeyConstraint(["outlet_id"], ["restaurant_outlets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["dining_session_id"], ["dining_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invoice_id"], ["dining_invoices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dining_session_id", "idempotency_key", name="uq_payment_intents_session_idempotency"),
    )
    op.create_index("ix_payment_intents_session", "payment_intents", ["dining_session_id"])
    op.create_index("ix_payment_intents_invoice", "payment_intents", ["invoice_id"])
    op.create_index("ix_payment_intents_status", "payment_intents", ["status"])

    # ── payment_attempts ───────────────────────────────────────────────────────
    op.create_table(
        "payment_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_intent_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "status",
            sa.Enum("initiated", "processing", "success", "failed", name="payment_attempt_status", native_enum=False),
            server_default="initiated",
            nullable=False,
        ),
        sa.Column("provider_reference", sa.String(length=120), nullable=True),
        sa.Column("failure_code", sa.String(length=50), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["payment_intent_id"], ["payment_intents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_attempts_intent", "payment_attempts", ["payment_intent_id"])

    # ── payment_events ─────────────────────────────────────────────────────────
    op.create_table(
        "payment_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_intent_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["payment_intent_id"], ["payment_intents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_events_intent", "payment_events", ["payment_intent_id"])

    # ── audit_logs ─────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outlet_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.String(length=120), nullable=True),
        sa.Column(
            "actor_type",
            sa.Enum("customer", "owner", "staff", name="audit_actor_type", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "action_type",
            sa.Enum(
                "price_change",
                "availability_override",
                "dish_create",
                "dish_update",
                "menu_publish",
                "hours_update",
                name="audit_action_type",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=60), nullable=False),
        sa.Column("target_id", sa.String(length=120), nullable=False),
        sa.Column("previous_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(length=60), server_default="api", nullable=False),
        sa.Column("confirmation_reference", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["outlet_id"], ["restaurant_outlets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_outlet_created", "audit_logs", ["outlet_id", "created_at"])
    op.create_index("ix_audit_logs_target", "audit_logs", ["target_type", "target_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action_type"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("payment_events")
    op.drop_table("payment_attempts")
    op.drop_table("payment_intents")
