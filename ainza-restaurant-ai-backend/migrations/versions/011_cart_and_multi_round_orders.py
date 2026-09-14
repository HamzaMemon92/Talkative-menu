"""cart and multi-round orders

Revision ID: 011_cart_and_multi_round_orders
Revises: 010_tables_and_dining_sessions
Create Date: 2026-09-10 05:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "011_cart_and_multi_round_orders"
down_revision: str | None = "010_tables_and_dining_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dining_carts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dining_session_id", sa.Uuid(), nullable=False),
        sa.Column("selected_offer_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="ck_dining_carts_version"),
        sa.ForeignKeyConstraint(["dining_session_id"], ["dining_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["selected_offer_id"], ["offers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dining_session_id"),
    )
    op.create_index("ix_dining_carts_session", "dining_carts", ["dining_session_id"])

    op.create_table(
        "cart_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cart_id", sa.Uuid(), nullable=False),
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=True),
        sa.Column("quantity", sa.SmallInteger(), nullable=False),
        sa.Column("customer_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity > 0 AND quantity <= 99", name="ck_cart_items_quantity"),
        sa.ForeignKeyConstraint(["cart_id"], ["dining_carts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["variant_id"], ["dish_variants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cart_items_cart", "cart_items", ["cart_id"])
    op.create_index("ix_cart_items_dish_id", "cart_items", ["dish_id"])
    op.create_index("ix_cart_items_variant_id", "cart_items", ["variant_id"])

    op.create_table(
        "cart_item_modifiers",
        sa.Column("cart_item_id", sa.Uuid(), nullable=False),
        sa.Column("modifier_option_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["cart_item_id"], ["cart_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["modifier_option_id"], ["modifier_options.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("cart_item_id", "modifier_option_id"),
        sa.UniqueConstraint(
            "cart_item_id", "modifier_option_id", name="uq_cart_item_modifier_option"
        ),
    )

    op.create_table(
        "dining_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dining_session_id", sa.Uuid(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("submitted", name="dining_order_status", native_enum=False),
            server_default="submitted",
            nullable=False,
        ),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("subtotal_before_discount", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("subtotal_after_discount", sa.Numeric(12, 2), nullable=False),
        sa.Column("selected_offer_id", sa.Uuid(), nullable=True),
        sa.Column("offer_name_snapshot", sa.String(length=200), nullable=True),
        sa.Column(
            "offer_type_snapshot",
            sa.Enum(
                "percentage",
                "flat",
                "combo_fixed_price",
                name="order_offer_type",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("round_number >= 1", name="ck_dining_orders_round_number"),
        sa.CheckConstraint(
            "subtotal_before_discount >= 0 AND discount_amount >= 0 "
            "AND subtotal_after_discount >= 0",
            name="ck_dining_orders_money",
        ),
        sa.ForeignKeyConstraint(["dining_session_id"], ["dining_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["selected_offer_id"], ["offers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dining_session_id", "round_number", name="uq_dining_orders_round"),
        sa.UniqueConstraint(
            "dining_session_id", "idempotency_key", name="uq_dining_orders_idempotency"
        ),
    )
    op.create_index("ix_dining_orders_session", "dining_orders", ["dining_session_id"])

    op.create_table(
        "dining_order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=True),
        sa.Column("dish_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("variant_name_snapshot", sa.String(length=150), nullable=True),
        sa.Column("quantity", sa.SmallInteger(), nullable=False),
        sa.Column("customer_note_snapshot", sa.Text(), nullable=True),
        sa.Column("catalog_unit_price_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column("special_unit_price_snapshot", sa.Numeric(12, 2), nullable=True),
        sa.Column("effective_base_unit_price_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column("modifier_unit_total_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column("configured_unit_price_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_subtotal_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_category_code_snapshot", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity > 0", name="ck_dining_order_items_quantity"),
        sa.CheckConstraint(
            "catalog_unit_price_snapshot >= 0 AND modifier_unit_total_snapshot >= 0 "
            "AND configured_unit_price_snapshot >= 0 AND line_subtotal_snapshot >= 0",
            name="ck_dining_order_items_money",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["dining_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["variant_id"], ["dish_variants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dining_order_items_order", "dining_order_items", ["order_id"])

    op.create_table(
        "dining_order_item_modifiers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_item_id", sa.Uuid(), nullable=False),
        sa.Column("modifier_option_id", sa.Uuid(), nullable=True),
        sa.Column("modifier_group_name_snapshot", sa.String(length=150), nullable=False),
        sa.Column("modifier_option_name_snapshot", sa.String(length=150), nullable=False),
        sa.Column("price_delta_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["order_item_id"], ["dining_order_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["modifier_option_id"], ["modifier_options.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dining_order_item_modifiers_order_item_id",
        "dining_order_item_modifiers",
        ["order_item_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dining_order_item_modifiers_order_item_id",
        table_name="dining_order_item_modifiers",
    )
    op.drop_table("dining_order_item_modifiers")
    op.drop_index("ix_dining_order_items_order", table_name="dining_order_items")
    op.drop_table("dining_order_items")
    op.drop_index("ix_dining_orders_session", table_name="dining_orders")
    op.drop_table("dining_orders")
    op.drop_table("cart_item_modifiers")
    op.drop_index("ix_cart_items_variant_id", table_name="cart_items")
    op.drop_index("ix_cart_items_dish_id", table_name="cart_items")
    op.drop_index("ix_cart_items_cart", table_name="cart_items")
    op.drop_table("cart_items")
    op.drop_index("ix_dining_carts_session", table_name="dining_carts")
    op.drop_table("dining_carts")
