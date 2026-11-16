"""Persist observer catch-up cursors on their original narration sources."""

import sqlalchemy as sa

from alembic import op

revision = "d9b3e5a7c903"
down_revision = "d9b3e5a7c902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("npc_recovery", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        batch.drop_column("npc_recovery")
