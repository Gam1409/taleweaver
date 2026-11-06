"""Keep optional per-reply portrait state separate from story prose."""

import sqlalchemy as sa

from alembic import op

revision = "d9b3e5a7c902"
down_revision = "c8a2d4f6b801"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("portrait_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        batch.drop_column("portrait_state")
