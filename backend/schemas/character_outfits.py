"""Reviewable, additive clothing drafts for existing template characters."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.engine.clothing.classification import classify_garment
from backend.engine.clothing.schema import Appearance
from backend.schemas.authoring_completion import OutfitItem


class CharacterOutfitDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    appearance: Appearance | None = None
    outfit: list[OutfitItem] = Field(default_factory=list, max_length=16)

    @field_validator("outfit")
    @classmethod
    def classify_items(cls, items: list[OutfitItem]) -> list[OutfitItem]:
        return [
            item.model_copy(update={"clothing": classify_garment(item.name, item.clothing)})
            for item in items
        ]


class CharacterOutfitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    target_type: Literal["npc", "protagonist"]
    target_id: str = Field(min_length=1, max_length=100)
    brief: str = Field(default="", max_length=2000)
    include_underwear: bool = False
    name: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=1000)
    character: str = Field(default="", max_length=1000)
    goal: str = Field(default="", max_length=1000)
    inventory_ids: list[str] = Field(default_factory=list, max_length=128)
