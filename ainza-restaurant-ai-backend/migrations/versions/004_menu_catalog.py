"""menu catalog foundation

Revision ID: 004_menu_catalog
Revises: 003_outlet_food_policy
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004_menu_catalog"
down_revision: str | None = "003_outlet_food_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False)


def upgrade() -> None:
    op.create_table(
        "menus",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("outlet_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            enum("draft", "published", name="menu_status"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_menus_name"),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outlet_id"], ["restaurant_outlets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_menus_restaurant_id", "menus", ["restaurant_id"])
    op.create_index("ix_menus_outlet_id", "menus", ["outlet_id"])
    op.create_table(
        "menu_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("menu_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_menu_categories_name"),
        sa.ForeignKeyConstraint(["menu_id"], ["menus.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_menu_categories_menu_id", "menu_categories", ["menu_id"])
    op.create_table(
        "cuisines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_cuisines_name"),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("restaurant_id", "name", name="uq_cuisines_restaurant_name"),
    )
    op.create_index("ix_cuisines_restaurant_id", "cuisines", ["restaurant_id"])
    op.create_table(
        "menu_cuisines",
        sa.Column("menu_id", sa.Uuid(), nullable=False),
        sa.Column("cuisine_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["menu_id"], ["menus.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cuisine_id"], ["cuisines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("menu_id", "cuisine_id"),
    )
    op.create_table(
        "ingredients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_ingredients_name"),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("restaurant_id", "name", name="uq_ingredients_restaurant_name"),
    )
    op.create_index("ix_ingredients_restaurant_id", "ingredients", ["restaurant_id"])
    op.create_table(
        "dishes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("menu_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("base_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column(
            "allergen_status",
            enum("unknown", "contains", "does_not_contain", name="allergen_status"),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "halal_override",
            enum("unknown", "halal", "not_halal", "not_applicable", name="halal_override"),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "spice_level",
            enum("unknown", "none", "mild", "medium", "hot", "extra_hot", name="spice_level"),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "provenance_source",
            enum("unknown", "owner_entered", name="provenance_source"),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "review_status",
            enum("unreviewed", "approved", "rejected", name="review_status"),
            nullable=False,
            server_default="unreviewed",
        ),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_dishes_name"),
        sa.CheckConstraint("base_price >= 0", name="ck_dishes_base_price"),
        sa.ForeignKeyConstraint(["menu_id"], ["menus.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["menu_categories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dishes_menu_id", "dishes", ["menu_id"])
    op.create_index("ix_dishes_category_id", "dishes", ["category_id"])
    op.create_table(
        "dish_variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint("price >= 0", name="ck_dish_variants_price"),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dish_variants_dish_id", "dish_variants", ["dish_id"])
    op.create_table(
        "dish_ingredients",
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column("ingredient_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("unit", sa.String(40), nullable=True),
        sa.Column("notes", sa.String(300), nullable=True),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("dish_id", "ingredient_id"),
    )
    op.create_table(
        "dish_dietary_statuses",
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            enum(
                "unknown",
                "vegetarian",
                "vegan",
                "eggetarian",
                "jain",
                "non_vegetarian",
                name="dietary_status",
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("dish_id", "status"),
    )
    op.create_table(
        "dish_badges",
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column(
            "badge",
            enum(
                "vegetarian",
                "vegan",
                "jain",
                "halal",
                "spicy",
                "chef_recommended",
                name="badge_code",
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("dish_id", "badge"),
    )
    op.create_table(
        "dish_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column("uri", sa.String(1000), nullable=False),
        sa.Column("alt_text", sa.String(300), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("width", sa.SmallInteger(), nullable=True),
        sa.Column("height", sa.SmallInteger(), nullable=True),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column(
            "approval_status",
            enum("unknown", "pending", "approved", "rejected", name="image_approval_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dish_images_dish_id", "dish_images", ["dish_id"])
    op.create_table(
        "modifier_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("min_selections", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("max_selections", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("min_selections >= 0", name="ck_modifier_groups_min"),
        sa.CheckConstraint("max_selections >= min_selections", name="ck_modifier_groups_max"),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_modifier_groups_dish_id", "modifier_groups", ["dish_id"])
    op.create_table(
        "modifier_options",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("price_delta", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.CheckConstraint("price_delta >= 0", name="ck_modifier_options_price_delta"),
        sa.ForeignKeyConstraint(["group_id"], ["modifier_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_modifier_options_group_id", "modifier_options", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_modifier_options_group_id", table_name="modifier_options")
    op.drop_table("modifier_options")
    op.drop_index("ix_modifier_groups_dish_id", table_name="modifier_groups")
    op.drop_table("modifier_groups")
    op.drop_index("ix_dish_images_dish_id", table_name="dish_images")
    op.drop_table("dish_images")
    op.drop_table("dish_badges")
    op.drop_table("dish_dietary_statuses")
    op.drop_table("dish_ingredients")
    op.drop_index("ix_dish_variants_dish_id", table_name="dish_variants")
    op.drop_table("dish_variants")
    op.drop_index("ix_dishes_category_id", table_name="dishes")
    op.drop_index("ix_dishes_menu_id", table_name="dishes")
    op.drop_table("dishes")
    op.drop_index("ix_ingredients_restaurant_id", table_name="ingredients")
    op.drop_table("ingredients")
    op.drop_table("menu_cuisines")
    op.drop_index("ix_cuisines_restaurant_id", table_name="cuisines")
    op.drop_table("cuisines")
    op.drop_index("ix_menu_categories_menu_id", table_name="menu_categories")
    op.drop_table("menu_categories")
    op.drop_index("ix_menus_outlet_id", table_name="menus")
    op.drop_index("ix_menus_restaurant_id", table_name="menus")
    op.drop_table("menus")
