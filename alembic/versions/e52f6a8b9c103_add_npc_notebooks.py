"""Add one current session-owned private notebook per NPC.

Revision ID: e52f6a8b9c103
Revises: ab17c8d9e602
"""

import sqlalchemy as sa

from alembic import op

revision = "e52f6a8b9c103"
down_revision = "ab17c8d9e602"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "npc_notebooks",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("game_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("npc_id", sa.String(100), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "npc_id"),
        sa.CheckConstraint("byte_size >= 1 AND byte_size <= 16000000", name="notebook_byte_size"),
        sa.CheckConstraint("revision >= 0", name="notebook_revision"),
    )
    for field in ("user_id", "session_id"):
        op.create_index(f"ix_npc_notebooks_{field}", "npc_notebooks", [field])


def downgrade() -> None:
    op.drop_table("npc_notebooks")
