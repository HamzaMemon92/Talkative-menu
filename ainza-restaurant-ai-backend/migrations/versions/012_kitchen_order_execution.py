"""kitchen order execution

Revision ID: 012_kitchen_order_execution
Revises: 011_cart_and_multi_round_orders
Create Date: 2026-09-10 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "012_kitchen_order_execution"
down_revision: str | None = "011_cart_and_multi_round_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "dining_orders",
        "status",
        existing_type=sa.String(length=9),
        type_=sa.String(length=20),
        existing_nullable=False,
        existing_server_default="submitted",
    )
    op.create_table(
        "kitchen_tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outlet_id", sa.Uuid(), nullable=False),
        sa.Column("dining_order_id", sa.Uuid(), nullable=False),
        sa.Column("table_label_snapshot", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "in_progress",
                "ready",
                "served",
                name="kitchen_ticket_status",
                native_enum=False,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("served_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(trim(table_label_snapshot)) > 0", name="ck_kitchen_table_label"),
        sa.ForeignKeyConstraint(["outlet_id"], ["restaurant_outlets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dining_order_id"], ["dining_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dining_order_id", name="uq_kitchen_tickets_order"),
    )
    op.create_index(
        "ix_kitchen_tickets_outlet_status_created",
        "kitchen_tickets",
        ["outlet_id", "status", "created_at"],
    )
    op.create_index("ix_kitchen_tickets_order", "kitchen_tickets", ["dining_order_id"])

    op.create_table(
        "kitchen_ticket_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kitchen_ticket_id", sa.Uuid(), nullable=False),
        sa.Column("dining_order_item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "preparing",
                "ready",
                "served",
                name="kitchen_ticket_item_status",
                native_enum=False,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("served_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["kitchen_ticket_id"], ["kitchen_tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["dining_order_item_id"], ["dining_order_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dining_order_item_id", name="uq_kitchen_ticket_items_order_item"),
    )
    op.create_index("ix_kitchen_ticket_items_ticket", "kitchen_ticket_items", ["kitchen_ticket_id"])
    op.create_index("ix_kitchen_ticket_items_status", "kitchen_ticket_items", ["status"])


def downgrade() -> None:
    op.drop_index("ix_kitchen_ticket_items_status", table_name="kitchen_ticket_items")
    op.drop_index("ix_kitchen_ticket_items_ticket", table_name="kitchen_ticket_items")
    op.drop_table("kitchen_ticket_items")
    op.drop_index("ix_kitchen_tickets_order", table_name="kitchen_tickets")
    op.drop_index("ix_kitchen_tickets_outlet_status_created", table_name="kitchen_tickets")
    op.drop_table("kitchen_tickets")
    op.alter_column(
        "dining_orders",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=9),
        existing_nullable=False,
        existing_server_default="submitted",
    )
