"""Persist optional Living World defaults on adventure templates."""

import sqlalchemy as sa

from alembic import op

revision = "b6d8f0a2c413"
down_revision = "9a0c4e7b1d62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "adventure_templates", sa.Column("living_world_settings", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    with op.batch_alter_table("adventure_templates") as batch:
        batch.drop_column("living_world_settings")
