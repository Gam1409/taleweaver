"""Persist session-owned World Info sources, revision jobs and reviewed entries.

Revision ID: ab17c8d9e602
Revises: d9b3e5a7c904
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ab17c8d9e602"
down_revision: str | Sequence[str] | None = "d9b3e5a7c904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _identity() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _constraints(table: str) -> list[sa.Constraint]:
    return [
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f(f"fk_{table}_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["game_sessions.id"],
            name=op.f(f"fk_{table}_session_id_game_sessions"),
            ondelete="CASCADE",
        ),
    ]


def _indexes(table: str, fields: tuple[str, ...]) -> None:
    for field in fields:
        op.create_index(op.f(f"ix_{table}_{field}"), table, [field], unique=False)


def upgrade() -> None:
    op.create_table(
        "world_info_sources",
        *_identity(),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("published_revision", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        *_constraints("world_info_sources"),
    )
    _indexes("world_info_sources", ("user_id", "session_id"))
    op.create_table(
        "world_info_revisions",
        *_identity(),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("input_bytes", sa.Integer(), nullable=False),
        sa.Column("input_characters", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.Integer(), nullable=False),
        sa.Column("extraction_version", sa.Integer(), nullable=False),
        sa.Column("processing_language", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("cursor", sa.Integer(), nullable=False),
        sa.Column("total_batches", sa.Integer(), nullable=False),
        sa.Column("processed_characters", sa.Integer(), nullable=False),
        sa.Column("facts_count", sa.Integer(), nullable=False),
        sa.Column("entries_count", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("control_version", sa.Integer(), nullable=False),
        sa.Column("run_token", sa.String(36), nullable=True),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("lease_until", sa.Float(), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        *_constraints("world_info_revisions"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["world_info_sources.id"],
            name=op.f("fk_world_info_revisions_source_id_world_info_sources"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("source_id", "number", name=op.f("uq_world_info_revisions_source_id")),
    )
    _indexes("world_info_revisions", ("user_id", "session_id", "source_id"))
    op.create_table(
        "world_info_entries",
        *_identity(),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("source_revision_id", sa.String(36), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("group_name", sa.String(80), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("relations", sa.JSON(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("audience", sa.String(20), nullable=False),
        sa.Column("known_by", sa.JSON(), nullable=False),
        sa.Column("unresolved_known_by", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("edited", sa.Boolean(), nullable=False),
        *_constraints("world_info_entries"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["world_info_sources.id"],
            name=op.f("fk_world_info_entries_source_id_world_info_sources"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["world_info_revisions.id"],
            name=op.f("fk_world_info_entries_source_revision_id_world_info_revisions"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "source_revision_id",
            "batch_index",
            "ordinal",
            name=op.f("uq_world_info_entries_source_revision_id"),
        ),
    )
    _indexes("world_info_entries", ("user_id", "session_id", "source_id", "source_revision_id"))


def downgrade() -> None:
    op.drop_table("world_info_entries")
    op.drop_table("world_info_revisions")
    op.drop_table("world_info_sources")
