"""Canonical summaries and durable control state for a rebuildable memory index."""

import uuid6
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin


class MemoryIndexState(Base, TimestampMixin):
    __tablename__ = "memory_index_states"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("adventure_templates.id", ondelete="SET NULL"), index=True
    )
    epoch: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    desired_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    indexed_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(400), nullable=True)


class MemorySummary(Base, TimestampMixin):
    __tablename__ = "memory_summaries"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid6.uuid7())
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    layer: Mapped[str] = mapped_column(String(30), nullable=False)
    npc_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    # None denotes legacy whole-message coverage; keys identify bounded source fragments.
    source_keys: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
