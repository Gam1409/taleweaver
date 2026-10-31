"""Add opt-in simulation persistence and independent real-time presence."""

import sqlalchemy as sa

from alembic import op

revision = "9a0c4e7b1d62"
down_revision = "2d9b7a4c8e31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("session_states", sa.Column("living_world", sa.JSON(), nullable=True))
    op.add_column("game_sessions", sa.Column("living_world_presence", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("game_sessions") as batch:
        batch.drop_column("living_world_presence")
    with op.batch_alter_table("session_states") as batch:
        batch.drop_column("living_world")
