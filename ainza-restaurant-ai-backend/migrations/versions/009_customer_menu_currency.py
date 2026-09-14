"""customer menu outlet currency

Revision ID: 009_customer_menu_currency
Revises: 008_merchandising_and_offers
Create Date: 2026-09-10 03:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "009_customer_menu_currency"
down_revision: str | None = "008_merchandising_and_offers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "restaurant_outlets",
        sa.Column("currency_code", sa.String(length=3), server_default="INR", nullable=False),
    )
    op.create_check_constraint(
        "ck_outlets_currency_code",
        "restaurant_outlets",
        "length(currency_code) = 3 AND currency_code = upper(currency_code)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_outlets_currency_code", "restaurant_outlets", type_="check")
    op.drop_column("restaurant_outlets", "currency_code")
