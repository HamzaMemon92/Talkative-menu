"""align Task 002C policy names with optional unknown-first semantics

Revision ID: 006_food_policy_semantics
Revises: 005_catalog_compliance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006_food_policy_semantics"
down_revision: str | None = "005_catalog_compliance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_outlet_food_policies_confirmation", "outlet_food_policies", type_="check"
    )
    op.add_column(
        "outlet_food_policies",
        sa.Column("halal_policy", sa.String(80), nullable=False, server_default="unknown"),
    )
    op.add_column("outlet_food_policies", sa.Column("notes", sa.String(1000), nullable=True))
    op.add_column(
        "outlet_food_policies",
        sa.Column("halal_certificate_reference", sa.String(500), nullable=True),
    )
    op.add_column(
        "outlet_food_policies",
        sa.Column("information_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("outlet_food_policies", "information_confirmed")
    op.drop_column("outlet_food_policies", "notes")
    op.drop_column("outlet_food_policies", "halal_policy")
    op.drop_column("outlet_food_policies", "halal_certificate_reference")
    op.create_check_constraint(
        "ck_outlet_food_policies_confirmation",
        "outlet_food_policies",
        "confirmation IS TRUE",
    )
