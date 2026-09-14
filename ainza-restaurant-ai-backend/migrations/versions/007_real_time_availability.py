"""real-time availability engine

Revision ID: 007_real_time_availability
Revises: 006_food_policy_semantics
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "007_real_time_availability"
down_revision: str | None = "006_food_policy_semantics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False)


def upgrade() -> None:
    op.create_table(
        "availability_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outlet_id", sa.Uuid(), nullable=False),
        sa.Column(
            "target_type",
            enum("dish", "ingredient", name="availability_target_type"),
            nullable=False,
        ),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column(
            "action",
            enum("mark_unavailable", "restore", name="availability_action"),
            nullable=False,
        ),
        sa.Column(
            "duration_mode",
            enum(
                "until_next_opening",
                "until_timestamp",
                "indefinite",
                name="availability_duration_mode",
            ),
            nullable=True,
        ),
        sa.Column("requested_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("computed_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reason_code",
            enum(
                "out_of_stock",
                "kitchen_issue",
                "owner_paused",
                "other",
                name="availability_reason_code",
            ),
            nullable=True,
        ),
        sa.Column("reason_note", sa.String(1000), nullable=True),
        sa.Column(
            "status",
            enum(
                "pending",
                "confirmed",
                "cancelled",
                "expired",
                name="availability_proposal_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("proposal_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("target_id IS NOT NULL", name="ck_availability_proposals_target_id"),
        sa.CheckConstraint(
            "(action = 'restore' AND duration_mode IS NULL) "
            "OR (action = 'mark_unavailable' AND duration_mode IS NOT NULL)",
            name="ck_availability_proposals_action_duration",
        ),
        sa.ForeignKeyConstraint(["outlet_id"], ["restaurant_outlets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_availability_proposals_outlet_id", "availability_proposals", ["outlet_id"])
    op.create_index("ix_availability_proposals_target_id", "availability_proposals", ["target_id"])
    op.create_index(
        "ix_availability_proposals_outlet_status",
        "availability_proposals",
        ["outlet_id", "status"],
    )

    op.create_table(
        "availability_proposal_affected_dishes",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["proposal_id"], ["availability_proposals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("proposal_id", "dish_id"),
    )

    op.create_table(
        "dish_availability_overrides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reason_code",
            enum(
                "out_of_stock",
                "kitchen_issue",
                "owner_paused",
                "other",
                name="dish_availability_reason_code",
            ),
            nullable=False,
        ),
        sa.Column("reason_note", sa.String(1000), nullable=True),
        sa.Column("source_proposal_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"], ["availability_proposals.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dish_availability_overrides_dish_id",
        "dish_availability_overrides",
        ["dish_id"],
    )
    op.create_index(
        "ix_dish_availability_overrides_source_proposal_id",
        "dish_availability_overrides",
        ["source_proposal_id"],
    )
    op.create_index(
        "ix_dish_availability_overrides_dish_active",
        "dish_availability_overrides",
        ["dish_id", "revoked_at", "expires_at"],
    )

    op.create_table(
        "ingredient_availability_overrides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ingredient_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reason_code",
            enum(
                "out_of_stock",
                "kitchen_issue",
                "owner_paused",
                "other",
                name="ingredient_availability_reason_code",
            ),
            nullable=False,
        ),
        sa.Column("reason_note", sa.String(1000), nullable=True),
        sa.Column("source_proposal_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"], ["availability_proposals.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ingredient_availability_overrides_ingredient_id",
        "ingredient_availability_overrides",
        ["ingredient_id"],
    )
    op.create_index(
        "ix_ingredient_availability_overrides_source_proposal_id",
        "ingredient_availability_overrides",
        ["source_proposal_id"],
    )
    op.create_index(
        "ix_ingredient_availability_overrides_active",
        "ingredient_availability_overrides",
        ["ingredient_id", "revoked_at", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ingredient_availability_overrides_active",
        table_name="ingredient_availability_overrides",
    )
    op.drop_index(
        "ix_ingredient_availability_overrides_source_proposal_id",
        table_name="ingredient_availability_overrides",
    )
    op.drop_index(
        "ix_ingredient_availability_overrides_ingredient_id",
        table_name="ingredient_availability_overrides",
    )
    op.drop_table("ingredient_availability_overrides")
    op.drop_index(
        "ix_dish_availability_overrides_dish_active",
        table_name="dish_availability_overrides",
    )
    op.drop_index(
        "ix_dish_availability_overrides_source_proposal_id",
        table_name="dish_availability_overrides",
    )
    op.drop_index(
        "ix_dish_availability_overrides_dish_id",
        table_name="dish_availability_overrides",
    )
    op.drop_table("dish_availability_overrides")
    op.drop_table("availability_proposal_affected_dishes")
    op.drop_index("ix_availability_proposals_outlet_status", table_name="availability_proposals")
    op.drop_index("ix_availability_proposals_target_id", table_name="availability_proposals")
    op.drop_index("ix_availability_proposals_outlet_id", table_name="availability_proposals")
    op.drop_table("availability_proposals")
