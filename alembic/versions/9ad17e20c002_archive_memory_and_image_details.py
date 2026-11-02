"""Separate image audit data from hot session state and archive stale memory summaries."""

import json

import sqlalchemy as sa

from alembic import op

revision = "9ad17e20c002"
down_revision = "9ad17e20c001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_messages", sa.Column("illustration", sa.JSON(), nullable=True))
    op.add_column(
        "memory_summaries", sa.Column("archived", sa.Boolean(), nullable=False, server_default="0")
    )
    op.create_index("ix_memory_summaries_archived", "memory_summaries", ["archived"])
    connection = op.get_bind()
    states = sa.table(
        "session_states",
        sa.column("id"),
        sa.column("session_id"),
        sa.column("entity_states", sa.JSON()),
    )
    messages = sa.table(
        "chat_messages",
        sa.column("id"),
        sa.column("session_id"),
        sa.column("illustration", sa.JSON()),
    )
    for row in connection.execute(sa.select(states)).mappings():
        value = row["entity_states"] or {}
        if isinstance(value, str):
            value = json.loads(value)
        registry = value.get("__vn_illustrations__") or {}
        images = registry.get("images") or {}
        if not images:
            continue
        for message_id, image in images.items():
            connection.execute(
                messages.update()
                .where(messages.c.id == message_id, messages.c.session_id == row["session_id"])
                .values(illustration=image)
            )
        registry["images"] = {
            key: {"image_url": item.get("image_url"), "content_hash": item.get("content_hash")}
            for key, item in list(images.items())[-100:]
        }
        connection.execute(
            states.update().where(states.c.id == row["id"]).values(entity_states=value)
        )


def downgrade():
    # Restore details before dropping the per-message copy.
    connection = op.get_bind()
    states = sa.table(
        "session_states",
        sa.column("id"),
        sa.column("session_id"),
        sa.column("entity_states", sa.JSON()),
    )
    messages = sa.table(
        "chat_messages",
        sa.column("id"),
        sa.column("session_id"),
        sa.column("illustration", sa.JSON()),
    )
    for row in connection.execute(sa.select(states)).mappings():
        value = row["entity_states"] or {}
        images = value.setdefault("__vn_illustrations__", {}).setdefault("images", {})
        for message in connection.execute(
            sa.select(messages).where(messages.c.session_id == row["session_id"])
        ).mappings():
            if message["illustration"]:
                images[message["id"]] = message["illustration"]
        connection.execute(
            states.update().where(states.c.id == row["id"]).values(entity_states=value)
        )
    op.drop_index("ix_memory_summaries_archived", table_name="memory_summaries")
    op.drop_column("memory_summaries", "archived")
    op.drop_column("chat_messages", "illustration")
