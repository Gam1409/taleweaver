"""Session-owned source revisions and reviewed knowledge; vectors are derived."""

from typing import Any

import uuid6
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin


class WorldInfoSource(Base, TimestampMixin):
    __tablename__ = "world_info_sources"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid6.uuid7())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    current_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    published_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class WorldInfoRevision(Base, TimestampMixin):
    __tablename__ = "world_info_revisions"
    __table_args__ = (UniqueConstraint("source_id", "number"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid6.uuid7())
    )
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("world_info_sources.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    input_characters: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    extraction_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    processing_language: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="uploaded", nullable=False)
    cursor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_batches: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_characters: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    facts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    entries_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    control_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    run_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorldInfoEntry(Base, TimestampMixin):
    __tablename__ = "world_info_entries"
    __table_args__ = (UniqueConstraint("source_revision_id", "batch_index", "ordinal"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid6.uuid7())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("world_info_sources.id", ondelete="CASCADE"), index=True
    )
    source_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("world_info_revisions.id", ondelete="CASCADE"), index=True
    )
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    group_name: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    facts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    relations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="background_lore", nullable=False)
    audience: Mapped[str] = mapped_column(String(20), default="narrator_only", nullable=False)
    known_by: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    unresolved_known_by: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
