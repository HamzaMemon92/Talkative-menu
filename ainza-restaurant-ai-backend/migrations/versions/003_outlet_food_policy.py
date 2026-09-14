"""outlet food and dietary policy

Revision ID: 003_outlet_food_policy
Revises: 002_restaurant_onboarding
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003_outlet_food_policy"
down_revision: str | None = "002_restaurant_onboarding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outlet_food_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outlet_id", sa.Uuid(), nullable=False),
        sa.Column(
            "halal_status",
            sa.Enum(
                "unknown",
                "halal",
                "not_halal",
                "partial",
                name="halal_status",
                native_enum=False,
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "halal_certification_status",
            sa.Enum(
                "unknown",
                "certified",
                "not_certified",
                "pending",
                "not_applicable",
                name="halal_certification_status",
                native_enum=False,
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "pork_policy",
            sa.Enum("unknown", "served", "not_served", name="pork_policy", native_enum=False),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "alcohol_policy",
            sa.Enum("unknown", "served", "not_served", name="alcohol_policy", native_enum=False),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("confirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("confirmation IS TRUE", name="ck_outlet_food_policies_confirmation"),
        sa.ForeignKeyConstraint(["outlet_id"], ["restaurant_outlets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outlet_id"),
    )


def downgrade() -> None:
    op.drop_table("outlet_food_policies")
