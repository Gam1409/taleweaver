"""Store the latest turn's pre-action snapshot and recovery backup."""

import sqlalchemy as sa

from alembic import op

revision = "2d9b7a4c8e31"
down_revision = "1c8a6f3e7b20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "turn_replays",
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("game_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("backup", sa.JSON(), nullable=True),
        sa.Column("input_text", sa.String(), nullable=False),
        sa.Column("assistant_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("turn_replays")
