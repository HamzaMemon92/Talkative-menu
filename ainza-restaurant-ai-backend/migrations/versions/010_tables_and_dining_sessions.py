"""tables and dining sessions

Revision ID: 010_tables_and_dining_sessions
Revises: 009_customer_menu_currency
Create Date: 2026-09-10 04:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010_tables_and_dining_sessions"
down_revision: str | None = "009_customer_menu_currency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "restaurant_tables",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outlet_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("normalized_label", sa.String(length=120), nullable=False),
        sa.Column("area_name", sa.String(length=120), nullable=True),
        sa.Column("capacity", sa.SmallInteger(), nullable=True),
        sa.Column("display_order", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("public_qr_code", sa.String(length=96), nullable=False),
        sa.Column("qr_code_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(trim(label)) > 0", name="ck_restaurant_tables_label"),
        sa.CheckConstraint(
            "capacity IS NULL OR capacity > 0", name="ck_restaurant_tables_capacity"
        ),
        sa.CheckConstraint("display_order >= 0", name="ck_restaurant_tables_display_order"),
        sa.ForeignKeyConstraint(["outlet_id"], ["restaurant_outlets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_restaurant_tables_outlet_id", "restaurant_tables", ["outlet_id"])
    op.create_index(
        "ix_restaurant_tables_outlet_order",
        "restaurant_tables",
        ["outlet_id", "display_order", "label"],
    )
    op.create_index(
        "uq_restaurant_tables_public_qr_code",
        "restaurant_tables",
        ["public_qr_code"],
        unique=True,
    )
    op.create_index(
        "uq_restaurant_tables_outlet_active_label",
        "restaurant_tables",
        ["outlet_id", "normalized_label"],
        unique=True,
        postgresql_where=sa.text("is_active"),
        sqlite_where=sa.text("is_active = 1"),
    )

    op.create_table(
        "dining_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("table_id", sa.Uuid(), nullable=False),
        sa.Column("public_session_token", sa.String(length=96), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "closed", name="dining_session_status", native_enum=False),
            server_default="open",
            nullable=False,
        ),
        sa.Column("party_size", sa.SmallInteger(), nullable=True),
        sa.Column(
            "started_via",
            sa.Enum("qr", "manual", name="dining_session_started_via", native_enum=False),
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "party_size IS NULL OR party_size > 0", name="ck_dining_sessions_party_size"
        ),
        sa.CheckConstraint(
            "(status = 'open' AND closed_at IS NULL) OR "
            "(status = 'closed' AND closed_at IS NOT NULL)",
            name="ck_dining_sessions_status_closed_at",
        ),
        sa.ForeignKeyConstraint(["table_id"], ["restaurant_tables.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dining_sessions_table_id", "dining_sessions", ["table_id"])
    op.create_index("ix_dining_sessions_table_status", "dining_sessions", ["table_id", "status"])
    op.create_index(
        "uq_dining_sessions_public_session_token",
        "dining_sessions",
        ["public_session_token"],
        unique=True,
    )
    op.create_index(
        "uq_dining_sessions_one_open_per_table",
        "dining_sessions",
        ["table_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
        sqlite_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index("uq_dining_sessions_one_open_per_table", table_name="dining_sessions")
    op.drop_index("uq_dining_sessions_public_session_token", table_name="dining_sessions")
    op.drop_index("ix_dining_sessions_table_status", table_name="dining_sessions")
    op.drop_index("ix_dining_sessions_table_id", table_name="dining_sessions")
    op.drop_table("dining_sessions")
    op.drop_index("uq_restaurant_tables_outlet_active_label", table_name="restaurant_tables")
    op.drop_index("uq_restaurant_tables_public_qr_code", table_name="restaurant_tables")
    op.drop_index("ix_restaurant_tables_outlet_order", table_name="restaurant_tables")
    op.drop_index("ix_restaurant_tables_outlet_id", table_name="restaurant_tables")
    op.drop_table("restaurant_tables")
