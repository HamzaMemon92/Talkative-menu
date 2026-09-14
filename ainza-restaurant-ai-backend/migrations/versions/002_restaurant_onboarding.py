"""restaurant onboarding foundation

Revision ID: 002_restaurant_onboarding
Revises:
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002_restaurant_onboarding"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "restaurants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "inactive", name="restaurant_status", native_enum=False),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "onboarding_status",
            sa.Enum(
                "draft",
                "ready_for_menu",
                name="onboarding_status",
                native_enum=False,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_restaurants_name"),
        sa.CheckConstraint("length(trim(slug)) > 0", name="ck_restaurants_slug"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_restaurants_slug", "restaurants", ["slug"], unique=False)
    op.create_table(
        "restaurant_outlets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address_line1", sa.String(length=250), nullable=False),
        sa.Column("address_line2", sa.String(length=250), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=100), nullable=False),
        sa.Column("postal_code", sa.String(length=20), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False, server_default="IN"),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Kolkata"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_restaurant_outlets_name"),
        sa.CheckConstraint(
            "length(country) = 2 AND country = upper(country)", name="ck_outlets_country"
        ),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_restaurant_outlets_restaurant_id", "restaurant_outlets", ["restaurant_id"])
    op.create_index(
        "uq_restaurant_outlets_primary",
        "restaurant_outlets",
        ["restaurant_id"],
        unique=True,
        sqlite_where=sa.text("is_primary = 1"),
        postgresql_where=sa.text("is_primary"),
    )
    op.create_table(
        "weekly_operating_intervals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outlet_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("opens_at", sa.Time(), nullable=True),
        sa.Column("closes_at", sa.Time(), nullable=True),
        sa.Column("is_full_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_operating_intervals_weekday"),
        sa.CheckConstraint(
            "(is_full_day IS TRUE AND opens_at IS NULL AND closes_at IS NULL) "
            "OR (is_full_day IS FALSE AND opens_at IS NOT NULL AND closes_at IS NOT NULL "
            "AND opens_at <> closes_at)",
            name="ck_operating_intervals_shape",
        ),
        sa.ForeignKeyConstraint(["outlet_id"], ["restaurant_outlets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_weekly_operating_intervals_outlet_id", "weekly_operating_intervals", ["outlet_id"]
    )
    op.create_table(
        "outlet_tax_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outlet_id", sa.Uuid(), nullable=False),
        sa.Column("legal_business_name", sa.String(length=200), nullable=True),
        sa.Column("restaurant_type", sa.String(length=50), nullable=True),
        sa.Column("gst_registered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gst_state_code", sa.String(length=2), nullable=True),
        sa.Column("gstin", sa.String(length=15), nullable=True),
        sa.Column("gstin_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("configured_tax_rate_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("prices_include_tax", sa.Boolean(), nullable=True),
        sa.Column(
            "tax_configuration_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        # Compatibility flags from the initial Task 002 implementation.
        sa.Column(
            "no_auto_tax_rates_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("tax_rates_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "configured_tax_rate_percent IS NULL OR "
            "(configured_tax_rate_percent >= 0 AND configured_tax_rate_percent <= 100)",
            name="ck_tax_profiles_rate_range",
        ),
        sa.CheckConstraint(
            "gst_state_code IS NULL OR length(gst_state_code) = 2",
            name="ck_tax_profiles_state_code",
        ),
        sa.ForeignKeyConstraint(["outlet_id"], ["restaurant_outlets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outlet_id"),
    )


def downgrade() -> None:
    op.drop_table("outlet_tax_profiles")
    op.drop_index(
        "ix_weekly_operating_intervals_outlet_id", table_name="weekly_operating_intervals"
    )
    op.drop_table("weekly_operating_intervals")
    op.drop_index("uq_restaurant_outlets_primary", table_name="restaurant_outlets")
    op.drop_index("ix_restaurant_outlets_restaurant_id", table_name="restaurant_outlets")
    op.drop_table("restaurant_outlets")
    op.drop_index("ix_restaurants_slug", table_name="restaurants")
    op.drop_table("restaurants")
