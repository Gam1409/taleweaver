from typing import Any

import uuid6
from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TimestampMixin


class GameSession(Base, TimestampMixin):
    __tablename__ = "game_sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid6.uuid7()), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    avatar_id: Mapped[str] = mapped_column(String(36), ForeignKey("avatars.id"), nullable=False)
    template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("adventure_templates.id", ondelete="SET NULL"), nullable=True
    )

    # Denormalized fields to preserve history if template is deleted
    adventure_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    adventure_image_url: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    status_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    playtime_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    playtime_last_seen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    living_world_presence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    copied_from_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("game_sessions.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    state = relationship(
        "SessionState", back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    checkpoints = relationship(
        "SessionCheckpoint", back_populates="session", cascade="all, delete-orphan"
    )
