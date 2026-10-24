"""Add durable per-message NPC journal tasks.

Revision ID: f81c9d2a4b60
Revises: e70ab891c79f
"""

import sqlalchemy as sa

from alembic import op

revision = "f81c9d2a4b60"
down_revision = "e70ab891c79f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        batch.add_column(sa.Column("npc_journal", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        batch.drop_column("npc_journal")
