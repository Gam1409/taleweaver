"""add memory index state and source backed summaries

Revision ID: 3a44969dc075
Revises: 353aa8ad41f8
Create Date: 2026-10-25 20:05:36.271058
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a44969dc075"
down_revision: Union[str, Sequence[str], None] = "353aa8ad41f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_index_states",
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("template_id", sa.String(length=36), nullable=True),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("desired_revision", sa.Integer(), nullable=False),
        sa.Column("indexed_revision", sa.Integer(), nullable=False),
        sa.Column("signature", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_until", sa.Float(), nullable=True),
        sa.Column("last_error", sa.String(length=400), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["game_sessions.id"],
            name=op.f("fk_memory_index_states_session_id_game_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["adventure_templates.id"],
            name=op.f("fk_memory_index_states_template_id_adventure_templates"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_memory_index_states_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_memory_index_states")),
    )
    with op.batch_alter_table("memory_index_states", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_memory_index_states_template_id"), ["template_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_memory_index_states_user_id"), ["user_id"], unique=False
        )

    op.create_table(
        "memory_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("layer", sa.String(length=30), nullable=False),
        sa.Column("npc_id", sa.String(length=100), nullable=True),
        sa.Column("scene_id", sa.String(length=100), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_message_ids", sa.JSON(), nullable=False),
        sa.Column("source_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["game_sessions.id"],
            name=op.f("fk_memory_summaries_session_id_game_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_memory_summaries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_summaries")),
    )
    with op.batch_alter_table("memory_summaries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_memory_summaries_session_id"), ["session_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_memory_summaries_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("memory_summaries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_memory_summaries_user_id"))
        batch_op.drop_index(batch_op.f("ix_memory_summaries_session_id"))

    op.drop_table("memory_summaries")
    with op.batch_alter_table("memory_index_states", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_memory_index_states_user_id"))
        batch_op.drop_index(batch_op.f("ix_memory_index_states_template_id"))

    op.drop_table("memory_index_states")
