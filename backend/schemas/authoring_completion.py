"""Typed completion proposals; existing facts are merged, never silently replaced."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.engine.clothing.schema import Appearance, Garment
from backend.engine.personality.profile import PersonalityProfile
from backend.schemas.character_identity import CharacterIdentityFields

EquipmentSlot = Literal[
    "Head",
    "Chest",
    "Arms",
    "Legs",
    "Hands",
    "Feet",
    "Ring_1",
    "Ring_2",
    "Neck",
    "MainHand",
    "OffHand",
]


class OutfitItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    item_id: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    wearable_slots: list[EquipmentSlot] = Field(min_length=1, max_length=4)
    clothing: Garment


class CharacterCompletion(CharacterIdentityFields):
    model_config = ConfigDict(extra="forbid")
    outfit_exemption: str | None = Field(default=None, min_length=1, max_length=300)
    personality_profile: PersonalityProfile | None = None
    appearance: Appearance | None = None
    outfit: list[OutfitItem] = Field(default_factory=list, max_length=8)


class WearableCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wearable_slots: list[EquipmentSlot] | None = Field(default=None, min_length=1, max_length=4)
    clothing: Garment | None = None
