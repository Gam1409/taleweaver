"""Keep Debug message identity across reloads, copies and prompt selection."""

import sqlalchemy as sa

from alembic import op

revision = "d9b3e5a7c904"
down_revision = "d9b3e5a7c903"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("is_debug", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        batch.drop_column("is_debug")
