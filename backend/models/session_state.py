from typing import Any

import uuid6
from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from backend.models.base import Base, TimestampMixin


class SessionState(Base, TimestampMixin):
    __tablename__ = "session_states"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid6.uuid7()), nullable=False
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_sessions.id"), nullable=False
    )

    # Denormalized fields for easier querying
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("adventure_templates.id", ondelete="SET NULL"), nullable=True
    )
    avatar_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("avatars.id"), nullable=True
    )

    # Current Runtime State
    current_scene_id: Mapped[str] = mapped_column(String(100), nullable=False, default="START")
    in_game_time: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_memory_turns: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    time_system: Mapped[str] = mapped_column(String(20), default="calendar", nullable=False)
    time_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    inventory: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True, default=[])

    # Progress trackers
    entity_states: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default={})
    exit_states: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default={})
    discovered_scenes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=[])
    quests: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True, default=[])
    world_memories: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, default=[]
    )
    world_rumors: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, default=[]
    )
    compressed_history: Mapped[dict[str, Any] | str | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    living_world: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=None)
    enable_history_compression: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    start_datetime: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Session-specific overrides/copies from template
    plot: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    rules: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    walkthrough: Mapped[str | None] = mapped_column(String(20000), nullable=True)
    completed_condition: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    gameover_condition: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    completed_guard_expression: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    gameover_guard_expression: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Active Sequence Tracking
    active_sequence_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active_sequence_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    tts_director_notes: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    selected_image_styles: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    selected_tone: Mapped[dict[str, Any] | str | None] = mapped_column(JSON, nullable=True)

    # Runtime flags
    is_completed: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)
    is_debug_enabled: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)
    is_walkthrough_revealed: Mapped[bool | None] = mapped_column(
        Boolean, default=False, nullable=True
    )
    allow_dynamic_items: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    session = relationship("GameSession", back_populates="state")

    # Legacy aliases for backward compatibility during migration rollout.
    adventure_id = synonym("template_id")
    scene_id = synonym("current_scene_id")
