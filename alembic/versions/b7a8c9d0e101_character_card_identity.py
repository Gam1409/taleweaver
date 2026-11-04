"""Add optional gender and age to NPC and protagonist cards."""

import sqlalchemy as sa

from alembic import op

revision = "b7a8c9d0e101"
down_revision = "9ad17e20c002"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("avatars", "world_entities"):
        op.add_column(table, sa.Column("gender", sa.String(80), nullable=True))
        op.add_column(table, sa.Column("age_years", sa.Integer(), nullable=True))


def downgrade():
    for table in ("avatars", "world_entities"):
        op.drop_column(table, "age_years")
        op.drop_column(table, "gender")
