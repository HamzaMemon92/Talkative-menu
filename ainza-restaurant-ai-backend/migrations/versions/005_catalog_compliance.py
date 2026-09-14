"""complete Phase B catalog compliance fields and constraints

Revision ID: 005_catalog_compliance
Revises: 004_menu_catalog
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005_catalog_compliance"
down_revision: str | None = "004_menu_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add(table: str, column: sa.Column[object]) -> None:
    op.add_column(table, column)


def upgrade() -> None:
    _add("menu_categories", sa.Column("slug", sa.String(180), nullable=True))
    _add(
        "menu_categories",
        sa.Column("display_order", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    _add(
        "menu_categories",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    _add("cuisines", sa.Column("outlet_id", sa.Uuid(), nullable=True))
    _add("cuisines", sa.Column("slug", sa.String(120), nullable=True))
    _add("cuisines", sa.Column("normalized_slug", sa.String(120), nullable=True))
    _add("cuisines", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    _add("ingredients", sa.Column("outlet_id", sa.Uuid(), nullable=True))
    _add("ingredients", sa.Column("normalized_name", sa.String(150), nullable=True))
    _add(
        "ingredients",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    _add("dishes", sa.Column("ingredient_description", sa.Text(), nullable=True))
    _add("dishes", sa.Column("item_type", sa.String(20), nullable=False, server_default="food"))
    _add(
        "dishes",
        sa.Column(
            "dietary_classification", sa.String(30), nullable=False, server_default="unknown"
        ),
    )
    _add(
        "dishes", sa.Column("jain_status", sa.String(20), nullable=False, server_default="unknown")
    )
    _add(
        "dishes", sa.Column("vegan_status", sa.String(20), nullable=False, server_default="unknown")
    )
    _add(
        "dishes", sa.Column("halal_status", sa.String(30), nullable=False, server_default="unknown")
    )
    _add("dishes", sa.Column("serves_min", sa.SmallInteger(), nullable=True))
    _add("dishes", sa.Column("serves_max", sa.SmallInteger(), nullable=True))
    _add("dishes", sa.Column("preparation_time_minutes", sa.SmallInteger(), nullable=True))
    _add("dishes", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    _add(
        "dishes", sa.Column("display_order", sa.SmallInteger(), nullable=False, server_default="0")
    )
    _add(
        "dishes",
        sa.Column(
            "allergen_information_status", sa.String(30), nullable=False, server_default="unknown"
        ),
    )
    _add("dishes", sa.Column("allergen_notes", sa.Text(), nullable=True))
    _add("dishes", sa.Column("tax_category_code", sa.String(50), nullable=True))
    _add(
        "dishes",
        sa.Column("catalog_source", sa.String(30), nullable=False, server_default="manual"),
    )
    _add("dish_variants", sa.Column("normalized_name", sa.String(150), nullable=True))
    _add(
        "dish_variants",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    _add(
        "dish_variants",
        sa.Column("display_order", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    _add(
        "dish_variants",
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    _add(
        "dish_ingredients",
        sa.Column(
            "is_required_for_availability", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    _add("dish_images", sa.Column("variant_id", sa.Uuid(), nullable=True))
    _add("dish_images", sa.Column("storage_key", sa.String(1000), nullable=True))
    _add("dish_images", sa.Column("source_url", sa.String(2000), nullable=True))
    _add(
        "dish_images",
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add(
        "dish_images",
        sa.Column("catalog_source", sa.String(30), nullable=False, server_default="manual"),
    )
    _add(
        "dish_images",
        sa.Column("review_status", sa.String(30), nullable=False, server_default="confirmed"),
    )
    _add(
        "modifier_groups",
        sa.Column("display_order", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    _add(
        "modifier_groups",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    _add(
        "modifier_options",
        sa.Column("display_order", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    _add(
        "modifier_options",
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    _add(
        "modifier_options",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "dish_cuisines",
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column("cuisine_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cuisine_id"], ["cuisines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("dish_id", "cuisine_id"),
    )
    op.create_index("ix_dish_cuisines_cuisine_id", "dish_cuisines", ["cuisine_id"])
    op.create_unique_constraint(
        "uq_menu_categories_menu_slug", "menu_categories", ["menu_id", "slug"]
    )
    op.create_unique_constraint(
        "uq_cuisines_restaurant_slug", "cuisines", ["restaurant_id", "slug"]
    )
    op.create_unique_constraint(
        "uq_ingredients_restaurant_normalized_name",
        "ingredients",
        ["restaurant_id", "normalized_name"],
    )
    op.create_unique_constraint(
        "uq_dish_variants_dish_name", "dish_variants", ["dish_id", "normalized_name"]
    )
    op.execute(
        "UPDATE dish_images SET storage_key = uri WHERE storage_key IS NULL AND uri IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_dish_images_location",
        "dish_images",
        "storage_key IS NOT NULL OR source_url IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("uq_dish_variants_dish_name", "dish_variants", type_="unique")
    op.drop_constraint("ck_dish_images_location", "dish_images", type_="check")
    op.drop_constraint("uq_ingredients_restaurant_normalized_name", "ingredients", type_="unique")
    op.drop_constraint("uq_cuisines_restaurant_slug", "cuisines", type_="unique")
    op.drop_constraint("uq_menu_categories_menu_slug", "menu_categories", type_="unique")
    op.drop_index("ix_dish_cuisines_cuisine_id", table_name="dish_cuisines")
    op.drop_table("dish_cuisines")
