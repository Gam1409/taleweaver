"""Versioned neutral visual facts; clothing refers to existing canonical possessions."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

Region = Literal["head", "torso", "arms", "pelvis", "legs", "feet", "hands"]
REGIONS: tuple[Region, ...] = ("head", "torso", "arms", "pelvis", "legs", "feet", "hands")


class _VisualModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Appearance(_VisualModel):
    age_years: Annotated[StrictInt, Field(ge=0, le=100000)] | None = None
    hair: str = Field(default="", max_length=160)
    eyes: str = Field(default="", max_length=100)
    build: str = Field(default="", max_length=160)
    features: str = Field(default="", max_length=400)


class Garment(_VisualModel):
    layer: Annotated[StrictInt, Field(ge=0, le=4)]
    coverage: list[Region] = Field(min_length=1, max_length=7)
    opaque: StrictBool = True
    underwear: StrictBool = False
    description: str = Field(default="", max_length=400)

    @field_validator("coverage")
    @classmethod
    def unique_coverage(cls, value: list[Region]) -> list[Region]:
        if len(value) != len(set(value)):
            raise ValueError("Coverage regions must be unique.")
        return value


class WornItem(_VisualModel):
    item_id: str = Field(min_length=1, max_length=100)
    uncovered_regions: list[Region] = Field(default_factory=list, max_length=7)

    @field_validator("uncovered_regions")
    @classmethod
    def unique_regions(cls, value: list[Region]) -> list[Region]:
        if len(value) != len(set(value)):
            raise ValueError("Uncovered regions must be unique.")
        return value


class VisualProfile(_VisualModel):
    version: Literal[1] = 1
    appearance: Appearance = Field(default_factory=Appearance)
    worn: list[WornItem] = Field(default_factory=list, max_length=32)

    @field_validator("worn")
    @classmethod
    def unique_items(cls, value: list[WornItem]) -> list[WornItem]:
        if len(value) != len({item.item_id for item in value}):
            raise ValueError("A garment can only be worn once.")
        return value
