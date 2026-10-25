"""persist character visual profiles

Revision ID: 353aa8ad41f8
Revises: 43e51d8b2a06
Create Date: 2026-10-25 15:29:21.681109
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "353aa8ad41f8"
down_revision: Union[str, Sequence[str], None] = "43e51d8b2a06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("avatars", schema=None) as batch_op:
        batch_op.add_column(sa.Column("visual_profile", sa.JSON(), nullable=True))

    with op.batch_alter_table("world_entities", schema=None) as batch_op:
        batch_op.add_column(sa.Column("visual_profile", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("world_entities", schema=None) as batch_op:
        batch_op.drop_column("visual_profile")

    with op.batch_alter_table("avatars", schema=None) as batch_op:
        batch_op.drop_column("visual_profile")
