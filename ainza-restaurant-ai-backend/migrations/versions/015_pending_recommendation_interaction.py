"""persist pending recommendation interactions

Revision ID: 015_pending_reco
Revises: 014_customer_ai_conversations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "015_pending_reco"
down_revision: str | None = "014_customer_ai_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_conversations",
        sa.Column("pending_recommendation_interaction_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_conversations", "pending_recommendation_interaction_json")
