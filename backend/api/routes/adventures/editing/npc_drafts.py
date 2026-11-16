"""Bounded NPC authoring drafts shared by generation and explicit publication."""

from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from backend.api.routes.adventures.editing.item_generation import ItemDraft
from backend.engine.authoring_clothing_policy import allows_inner_layers
from backend.engine.clothing.classification import classify_garment
from backend.engine.clothing.schema import Appearance
from backend.engine.personality.profile import PersonalityProfile
from backend.schemas.character_identity import CharacterIdentityFields


class NpcItemDraft(ItemDraft):
    worn: StrictBool = False

    @model_validator(mode="after")
    def validate_possession(self) -> "NpcItemDraft":
        if not self.is_portable or self.item_type in {"SWITCH", "CONSTRUCTABLE"}:
            raise ValueError("NPC belongings must be portable inventory items")
        if self.worn and (self.item_type != "WEARABLE" or self.clothing is None):
            raise ValueError("Only clothing with garment metadata can be worn")
        if self.clothing:
            self.clothing = classify_garment(self.name, self.clothing)
        return self


class NpcDraft(CharacterIdentityFields):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=1000)
    goal: str = Field(default="", max_length=1000)
    character: str = Field(default="", max_length=1000)
    appearance: Appearance = Field(default_factory=Appearance)
    personality_profile: PersonalityProfile = Field(default_factory=PersonalityProfile)
    hp: int = Field(default=20, ge=1, le=100000)
    stamina: int = Field(default=20, ge=0, le=100000)
    mana: int = Field(default=0, ge=0, le=100000)
    moveable: StrictBool = False
    is_killable: StrictBool = True
    items: list[NpcItemDraft] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_items(self) -> "NpcDraft":
        names = [" ".join(item.name.casefold().split()) for item in self.items]
        if len(names) != len(set(names)):
            raise ValueError("Declare each belonging only once")
        self.appearance = self.appearance.model_copy(update={"age_years": self.age_years})
        return self


class NpcDraftRequest(CharacterIdentityFields):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    brief: str = Field(min_length=1, max_length=4000)
    scene_id: str = Field(min_length=1, max_length=30)
    include_clothing: StrictBool = True
    include_underwear: StrictBool = False
    include_items: StrictBool = True


class NpcCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    creation_id: UUID
    scene_id: str = Field(min_length=1, max_length=30)
    draft: NpcDraft


def check_inner_layers(manifest: dict | None, actor: object, *, requested: bool) -> None:
    if requested and not allows_inner_layers(manifest, actor):
        raise HTTPException(
            400,
            "Underwear requires saved mature-content and detailed-clothing settings, "
            "and an explicit adult age (18+) on the character.",
        )
