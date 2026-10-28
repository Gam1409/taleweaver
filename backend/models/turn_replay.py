"""One durable pre-turn snapshot and crash-recovery backup per session."""

from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin


class TurnReplay(Base, TimestampMixin):
    __tablename__ = "turn_replays"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    before: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    backup: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    input_text: Mapped[str] = mapped_column(String, nullable=False)
    assistant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
