"""Persist staged world generation and resumable requests.

Revision ID: 43e51d8b2a06
Revises: f81c9d2a4b60
"""

import sqlalchemy as sa

from alembic import op

revision = "43e51d8b2a06"
down_revision = "f81c9d2a4b60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("adventure_templates") as batch_op:
        batch_op.add_column(sa.Column("generation_request", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("generation_checkpoint", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("generation_run_id", sa.String(36), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("adventure_templates") as batch_op:
        batch_op.drop_column("generation_run_id")
        batch_op.drop_column("generation_checkpoint")
        batch_op.drop_column("generation_request")
