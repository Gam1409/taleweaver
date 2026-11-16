from typing import Any

import uuid6
from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin


class Character(Base, TimestampMixin):
    """
    User's character templates.
    """

    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid6.uuid7())
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(30), nullable=False)
    profile_image: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Generic base stats that can be mapped conceptually anywhere.
    # We initialize them statically to 10 as per rules.
    stats: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=lambda: {
            "strength": 10,
            "intelligence": 10,
            "wisdom": 10,
            "dexterity": 10,
            "charisma": 10,
            "armor_class": 10,
        },
        nullable=False,
    )

    # Core RPG Stats (explicit columns for consistency with Avatar)
    strength: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    intelligence: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    wisdom: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    dexterity: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    charisma: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    armor_class: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    # Empty starting gear and stuff
    inventory: Mapped[list[dict[str, Any] | str]] = mapped_column(
        JSON, default=list, nullable=False
    )

    equipment: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=lambda: {
            "Head": None,
            "Chest": None,
            "Arms": None,
            "Legs": None,
            "Hands": None,
            "Feet": None,
            "Ring_1": None,
            "Ring_2": None,
            "Neck": None,
            "MainHand": None,
            "OffHand": None,
        },
        nullable=False,
    )

    status_effects: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
