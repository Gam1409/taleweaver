"""Keep narration revisions and immutable provenance tokens.

Revision ID: c7e9a1b3d524
Revises: b6d8f0a2c413
"""

import sqlalchemy as sa

from alembic import op

revision = "c7e9a1b3d524"
down_revision = "b6d8f0a2c413"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        batch.add_column(sa.Column("revision_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("versions", sa.JSON(), nullable=True))

    op.create_table(
        "hook_runs",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("boundary_id", sa.String(36), primary_key=True),
        sa.Column("hook_name", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("hook_runs")
    with op.batch_alter_table("chat_messages") as batch:
        batch.drop_column("versions")
        batch.drop_column("revision_id")
