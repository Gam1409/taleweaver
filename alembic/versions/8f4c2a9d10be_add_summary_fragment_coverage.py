"""Track exact source fragments covered by memory summaries."""

import sqlalchemy as sa

from alembic import op

revision = "8f4c2a9d10be"
down_revision = "3a44969dc075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memory_summaries", sa.Column("source_keys", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("memory_summaries", "source_keys")
