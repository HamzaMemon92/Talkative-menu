"""billing tax invoice foundation

Revision ID: 013_billing_tax_invoice
Revises: 012_kitchen_order_execution
Create Date: 2026-09-10 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013_billing_tax_invoice"
down_revision: str | None = "012_kitchen_order_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dining_invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dining_session_id", sa.Uuid(), nullable=False),
        sa.Column("outlet_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_reference", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.Enum("finalized", name="dining_invoice_status", native_enum=False),
            server_default="finalized",
            nullable=False,
        ),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("subtotal_before_discount", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("subtotal_after_discount", sa.Numeric(12, 2), nullable=False),
        sa.Column("taxable_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_rate_snapshot", sa.Numeric(5, 2), nullable=False),
        sa.Column("prices_include_tax_snapshot", sa.Boolean(), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("invoice_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("restaurant_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("outlet_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("legal_business_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column(
            "restaurant_type_snapshot",
            sa.Enum(
                "standalone",
                "hotel_restaurant",
                "specified_premises",
                "other",
                name="invoice_restaurant_type",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("gst_registered_snapshot", sa.Boolean(), nullable=False),
        sa.Column("gstin_snapshot", sa.String(length=15), nullable=True),
        sa.Column("state_snapshot", sa.String(length=100), nullable=True),
        sa.Column("country_code_snapshot", sa.String(length=2), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "subtotal_before_discount >= 0 AND discount_total >= 0 "
            "AND subtotal_after_discount >= 0 AND taxable_amount >= 0 "
            "AND tax_amount >= 0 AND invoice_total >= 0",
            name="ck_dining_invoices_money",
        ),
        sa.CheckConstraint(
            "tax_rate_snapshot >= 0 AND tax_rate_snapshot <= 100",
            name="ck_dining_invoices_tax_rate",
        ),
        sa.ForeignKeyConstraint(["dining_session_id"], ["dining_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["outlet_id"], ["restaurant_outlets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dining_session_id", name="uq_dining_invoices_session"),
        sa.UniqueConstraint(
            "dining_session_id", "idempotency_key", name="uq_dining_invoices_idempotency"
        ),
        sa.UniqueConstraint("invoice_reference"),
    )
    op.create_index(
        "ix_dining_invoices_outlet_created",
        "dining_invoices",
        ["outlet_id", "created_at"],
    )

    op.create_table(
        "dining_invoice_orders",
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("dining_order_id", sa.Uuid(), nullable=False),
        sa.Column("round_number_snapshot", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["dining_invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dining_order_id"], ["dining_orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("invoice_id", "dining_order_id"),
        sa.UniqueConstraint("invoice_id", "dining_order_id", name="uq_invoice_order_order"),
    )
    op.create_index("ix_dining_invoice_orders_invoice", "dining_invoice_orders", ["invoice_id"])

    op.create_table(
        "dining_invoice_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("dining_order_id", sa.Uuid(), nullable=False),
        sa.Column("dining_order_item_id", sa.Uuid(), nullable=True),
        sa.Column("round_number_snapshot", sa.Integer(), nullable=False),
        sa.Column("dish_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("variant_name_snapshot", sa.String(length=150), nullable=True),
        sa.Column("quantity", sa.SmallInteger(), nullable=False),
        sa.Column("configured_unit_price_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_subtotal_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column("customer_note_snapshot", sa.Text(), nullable=True),
        sa.Column("tax_category_code_snapshot", sa.String(length=50), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity > 0", name="ck_dining_invoice_lines_quantity"),
        sa.CheckConstraint(
            "configured_unit_price_snapshot >= 0 AND line_subtotal_snapshot >= 0",
            name="ck_dining_invoice_lines_money",
        ),
        sa.ForeignKeyConstraint(["invoice_id"], ["dining_invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dining_order_id"], ["dining_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["dining_order_item_id"], ["dining_order_items.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dining_invoice_lines_invoice",
        "dining_invoice_lines",
        ["invoice_id", "display_order"],
    )

    op.create_table(
        "dining_invoice_line_modifiers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_line_id", sa.Uuid(), nullable=False),
        sa.Column("modifier_option_id", sa.Uuid(), nullable=True),
        sa.Column("modifier_group_name_snapshot", sa.String(length=150), nullable=False),
        sa.Column("modifier_option_name_snapshot", sa.String(length=150), nullable=False),
        sa.Column("price_delta_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["invoice_line_id"], ["dining_invoice_lines.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dining_invoice_line_modifiers_line",
        "dining_invoice_line_modifiers",
        ["invoice_line_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dining_invoice_line_modifiers_line",
        table_name="dining_invoice_line_modifiers",
    )
    op.drop_table("dining_invoice_line_modifiers")
    op.drop_index("ix_dining_invoice_lines_invoice", table_name="dining_invoice_lines")
    op.drop_table("dining_invoice_lines")
    op.drop_index("ix_dining_invoice_orders_invoice", table_name="dining_invoice_orders")
    op.drop_table("dining_invoice_orders")
    op.drop_index("ix_dining_invoices_outlet_created", table_name="dining_invoices")
    op.drop_table("dining_invoices")
