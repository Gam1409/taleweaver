from typing import Any

import uuid6
from sqlalchemy import JSON, Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, synonym

from backend.models.base import Base, TimestampMixin


class WorldScene(Base, TimestampMixin):
    """
    A pre-generated location in the game world.
    """

    __tablename__ = "world_scenes"

    pk = Column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # Unique within an adventure (e.g. "FOREST_START")
    template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("adventure_templates.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=True
    )

    label: Mapped[str] = mapped_column(String(100), nullable=False)  # Human readable name
    description: Mapped[str] = mapped_column(
        String(2000), nullable=False
    )  # Atmospheric description
    image_url: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Scene visual link
    decorative_objects = Column(JSON, nullable=True)  # Static, non-interactable background details
    on_enter_scene_script: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    on_enter_scene_text: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    on_leave_scene_script: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    on_leave_scene_text: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    adventure_id = synonym("template_id")


class WorldExit(Base, TimestampMixin):
    """
    A connection between two scenes, with optional lock state.
    """

    __tablename__ = "world_exits"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid6.uuid7())
    )
    template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("adventure_templates.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=True
    )

    from_scene_id: Mapped[str] = mapped_column(String(50), nullable=False)
    to_scene_id: Mapped[str] = mapped_column(String(50), nullable=False)

    label: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "a heavy oak door"
    exit_type: Mapped[str] = mapped_column(String(20), default="one_way", nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lock_description = Column(
        String(255), nullable=True
    )  # e.g. "The door is bolted from the other side."
    code_to_unlock = Column(String(50), nullable=True)
    item_to_unlock = Column(String(50), nullable=True)
    rule_to_unlock = Column(String(500), nullable=True)
    unlock_expression = Column(String(500), nullable=True)
    on_open_exit_script: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    on_open_exit_text: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    on_exit_used_script: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    on_exit_used_text: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    on_unlock_success_script: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    on_unlock_success_text: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    on_unlock_failure_script: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    on_unlock_failure_text: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    adventure_id = synonym("template_id")


class WorldEntity(Base, TimestampMixin):
    """
    An NPC or Object that exists within the world and has a position.
    """

    __tablename__ = "world_entities"

    pk = Column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "OLD_LIBRARIAN"
    template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("adventure_templates.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=True
    )

    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "NPC" or "OBJECT"
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)

    current_scene_id: Mapped[str] = mapped_column(String(50), nullable=False)
    spatial_position = Column(String(255), nullable=True)  # e.g. "inside the desk"
    image_url: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Advanced Item Management
    item_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # e.g. "CONSUMABLE", "WEAPON", "KEY", "STATIC"
    wearable_slots: Mapped[list[str] | str | None] = mapped_column(
        JSON, nullable=True
    )  # e.g. ["Head", "Neck"]
    is_in_inventory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reveal_rule = Column(
        String(500), nullable=True
    )  # GM rule that triggers reveal (e.g. 'If the prot searches under the table')
    unlock_rule = Column(
        String(500), nullable=True
    )  # Optional hint rule for opening container items

    is_portable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    combination_ingredients: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True
    )  # List of entity IDs
    reveals_item_id = Column(String(50), nullable=True)
    is_final_state: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    state_comment = Column(String(1000), nullable=True)

    # NPC Specific Fields
    npc_type = Column(String(50), nullable=True)  # HUMANOID, ANIMAL, MONSTER, BEING
    movement_type = Column(String(50), nullable=True)  # STATIONARY, MOVABLE
    moveable: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # Whether NPC can move between scenes
    allowed_scenes = Column(
        JSON, default=list, nullable=True
    )  # Allowed scenes list; empty/null = all scenes
    notes = Column(
        String(1000), nullable=True
    )  # Dynamic status/condition notes for GM and narration
    goal = Column(String(1000), nullable=True)
    character = Column(String(1000), nullable=True)
    hp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_hp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mana: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_mana = Column(Integer, nullable=True)
    stamina: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_stamina = Column(Integer, nullable=True)
    voice = Column(String(50), nullable=True)  # Optional Google TTS voice for this NPC

    # Stat Modifiers
    stat_modifier_strength = Column(Integer, nullable=True)
    stat_modifier_dexterity = Column(Integer, nullable=True)
    stat_modifier_intelligence = Column(Integer, nullable=True)
    stat_modifier_wisdom = Column(Integer, nullable=True)
    stat_modifier_charisma = Column(Integer, nullable=True)
    stat_modifier_armor_class: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_attackable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_killable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Optional state, e.g. NPC inventory: [{"name": "Key", "id": "BRONZE_KEY"}]
    inventory: Mapped[list[Any] | None] = mapped_column(JSON, default=list, nullable=False)
    visual_profile = Column(JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, default=dict, nullable=False
    )  # For stats or dynamic state
    adventure_id = synonym("template_id")
