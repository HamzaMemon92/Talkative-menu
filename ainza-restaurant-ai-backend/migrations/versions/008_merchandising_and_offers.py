"""merchandising and offers engine

Revision ID: 008_merchandising_and_offers
Revises: 007_real_time_availability
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008_merchandising_and_offers"
down_revision: str | None = "007_real_time_availability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False)


def upgrade() -> None:
    status = enum("draft", "active", "paused", "deactivated", name="merchandising_status")
    op.create_table(
        "todays_specials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outlet_id", sa.Uuid(), nullable=False),
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=True),
        sa.Column("special_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", status, nullable=False, server_default="draft"),
        sa.Column("activation_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("display_note", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("special_price IS NULL OR special_price >= 0", name="ck_special_price"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_special_schedule"),
        sa.ForeignKeyConstraint(["outlet_id"], ["restaurant_outlets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["variant_id"], ["dish_variants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_todays_specials_outlet_id", "todays_specials", ["outlet_id"])
    op.create_index("ix_todays_specials_dish_id", "todays_specials", ["dish_id"])
    op.create_index("ix_todays_specials_variant_id", "todays_specials", ["variant_id"])
    op.create_index("ix_todays_specials_outlet_status", "todays_specials", ["outlet_id", "status"])

    op.create_table(
        "featured_dishes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outlet_id", sa.Uuid(), nullable=False),
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            enum("draft", "active", "paused", "deactivated", name="featured_dish_status"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("display_order", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("activation_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ck_featured_schedule"),
        sa.CheckConstraint("display_order >= 0", name="ck_featured_display_order"),
        sa.ForeignKeyConstraint(["outlet_id"], ["restaurant_outlets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_featured_dishes_outlet_id", "featured_dishes", ["outlet_id"])
    op.create_index("ix_featured_dishes_dish_id", "featured_dishes", ["dish_id"])
    op.create_index("ix_featured_dishes_outlet_status", "featured_dishes", ["outlet_id", "status"])

    op.create_table(
        "offers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outlet_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "offer_type",
            enum("percentage", "flat", "combo_fixed_price", name="offer_type"),
            nullable=False,
        ),
        sa.Column(
            "scope_type",
            enum("all_items", "selected_dishes", "selected_categories", name="offer_scope_type"),
            nullable=False,
            server_default="all_items",
        ),
        sa.Column(
            "status",
            enum("draft", "active", "paused", "deactivated", name="offer_status"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("minimum_subtotal", sa.Numeric(12, 2), nullable=True),
        sa.Column("discount_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("maximum_discount", sa.Numeric(12, 2), nullable=True),
        sa.Column("combo_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("activation_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_offers_name"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_offers_schedule"),
        sa.CheckConstraint(
            "minimum_subtotal IS NULL OR minimum_subtotal >= 0", name="ck_offers_minimum_subtotal"
        ),
        sa.CheckConstraint(
            "discount_value IS NULL OR discount_value >= 0", name="ck_offers_discount_value"
        ),
        sa.CheckConstraint(
            "maximum_discount IS NULL OR maximum_discount >= 0", name="ck_offers_maximum_discount"
        ),
        sa.CheckConstraint("combo_price IS NULL OR combo_price >= 0", name="ck_offers_combo_price"),
        sa.ForeignKeyConstraint(["outlet_id"], ["restaurant_outlets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_offers_outlet_id", "offers", ["outlet_id"])
    op.create_index("ix_offers_outlet_status", "offers", ["outlet_id", "status"])

    op.create_table(
        "offer_dish_scopes",
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("offer_id", "dish_id"),
    )
    op.create_table(
        "offer_category_scopes",
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["menu_categories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("offer_id", "category_id"),
    )
    op.create_table(
        "offer_combo_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=True),
        sa.Column("required_quantity", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("required_quantity >= 1", name="ck_combo_items_required_quantity"),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["variant_id"], ["dish_variants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "offer_id", "dish_id", "variant_id", name="uq_offer_combo_items_target"
        ),
    )
    op.create_index("ix_offer_combo_items_offer_id", "offer_combo_items", ["offer_id"])
    op.create_index("ix_offer_combo_items_dish_id", "offer_combo_items", ["dish_id"])
    op.create_index("ix_offer_combo_items_variant_id", "offer_combo_items", ["variant_id"])


def downgrade() -> None:
    op.drop_index("ix_offer_combo_items_variant_id", table_name="offer_combo_items")
    op.drop_index("ix_offer_combo_items_dish_id", table_name="offer_combo_items")
    op.drop_index("ix_offer_combo_items_offer_id", table_name="offer_combo_items")
    op.drop_table("offer_combo_items")
    op.drop_table("offer_category_scopes")
    op.drop_table("offer_dish_scopes")
    op.drop_index("ix_offers_outlet_status", table_name="offers")
    op.drop_index("ix_offers_outlet_id", table_name="offers")
    op.drop_table("offers")
    op.drop_index("ix_featured_dishes_outlet_status", table_name="featured_dishes")
    op.drop_index("ix_featured_dishes_dish_id", table_name="featured_dishes")
    op.drop_index("ix_featured_dishes_outlet_id", table_name="featured_dishes")
    op.drop_table("featured_dishes")
    op.drop_index("ix_todays_specials_outlet_status", table_name="todays_specials")
    op.drop_index("ix_todays_specials_variant_id", table_name="todays_specials")
    op.drop_index("ix_todays_specials_dish_id", table_name="todays_specials")
    op.drop_index("ix_todays_specials_outlet_id", table_name="todays_specials")
    op.drop_table("todays_specials")
