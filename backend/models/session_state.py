from typing import Any

import uuid6
from sqlalchemy import JSON, Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from backend.models.base import Base, TimestampMixin


class SessionState(Base, TimestampMixin):
    __tablename__ = "session_states"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid6.uuid7()))
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_sessions.id"), nullable=False
    )

    # Denormalized fields for easier querying
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("adventure_templates.id", ondelete="SET NULL"), nullable=True
    )
    avatar_id = Column(String(36), ForeignKey("avatars.id"), nullable=True)

    # Current Runtime State
    current_scene_id: Mapped[str] = mapped_column(String(100), nullable=False, default="START")
    in_game_time: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_memory_turns = Column(Integer, default=10, nullable=False)
    time_system = Column(String(20), default="calendar", nullable=False)
    time_config = Column(JSON, nullable=True)
    inventory = Column(JSON, nullable=True, default=[])

    # Progress trackers
    entity_states: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default={})
    exit_states: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default={})
    discovered_scenes = Column(JSON, nullable=True, default=[])
    quests: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True, default=[])
    world_memories: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, default=[]
    )
    world_rumors: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, default=[]
    )
    compressed_history: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    living_world: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=None)
    enable_history_compression = Column(Boolean, default=True, nullable=False)
    start_datetime = Column(String(36), nullable=True)

    # Session-specific overrides/copies from template
    plot = Column(String(5000), nullable=True)
    rules = Column(String(5000), nullable=True)
    walkthrough: Mapped[str | None] = mapped_column(String(20000), nullable=True)
    completed_condition = Column(String(1000), nullable=True)
    gameover_condition = Column(String(1000), nullable=True)
    completed_guard_expression = Column(String(2000), nullable=True)
    gameover_guard_expression = Column(String(2000), nullable=True)

    # Active Sequence Tracking
    active_sequence_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active_sequence_order = Column(Integer, default=1, nullable=False)
    tts_director_notes = Column(String(5000), nullable=True)
    selected_image_styles = Column(JSON, nullable=True)
    selected_tone = Column(JSON, nullable=True)

    # Runtime flags
    is_completed: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)
    is_debug_enabled = Column(Boolean, default=False)
    is_walkthrough_revealed = Column(Boolean, default=False)
    allow_dynamic_items = Column(Boolean, default=False, nullable=False)

    # Relationships
    session = relationship("GameSession", back_populates="state")

    # Legacy aliases for backward compatibility during migration rollout.
    adventure_id = synonym("template_id")
    scene_id = synonym("current_scene_id")
