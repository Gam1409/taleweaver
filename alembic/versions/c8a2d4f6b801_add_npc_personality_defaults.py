"""Persist optional NPC Personality defaults independently of saved sessions."""

import sqlalchemy as sa

from alembic import op

revision = "c8a2d4f6b801"
down_revision = "b7a8c9d0e101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "adventure_templates", sa.Column("npc_personality_settings", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    with op.batch_alter_table("adventure_templates") as batch:
        batch.drop_column("npc_personality_settings")
