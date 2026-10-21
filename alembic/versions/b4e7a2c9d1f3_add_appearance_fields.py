"""add appearance keywords for image prompts

Revision ID: b4e7a2c9d1f3
Revises: a9e3c1d5f7b2
Create Date: 2026-10-21 12:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4e7a2c9d1f3"
down_revision = "a9e3c1d5f7b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("avatars", schema=None) as batch_op:
        batch_op.add_column(sa.Column("appearance", sa.String(length=100), nullable=True))
    with op.batch_alter_table("world_entities", schema=None) as batch_op:
        batch_op.add_column(sa.Column("appearance", sa.String(length=100), nullable=True))
    with op.batch_alter_table("adventure_templates", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cover_appearance", sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("adventure_templates", schema=None) as batch_op:
        batch_op.drop_column("cover_appearance")
    with op.batch_alter_table("world_entities", schema=None) as batch_op:
        batch_op.drop_column("appearance")
    with op.batch_alter_table("avatars", schema=None) as batch_op:
        batch_op.drop_column("appearance")
