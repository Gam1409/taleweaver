"""Versioned neutral visual facts; clothing refers to existing canonical possessions."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictBool,
    StrictInt,
    field_validator,
    model_serializer,
    model_validator,
)

from backend.engine.clothing.body_schema import BodyLayout, BodySlot, WearSource

Region = Literal["head", "torso", "arms", "pelvis", "legs", "feet", "hands"]
REGIONS: tuple[Region, ...] = ("head", "torso", "arms", "pelvis", "legs", "feet", "hands")


class _VisualModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_serializer(mode="wrap")
    def legacy_shape(self, handler: SerializerFunctionWrapHandler) -> dict:
        result: dict = handler(self)
        for key in ("body", "attachment_slot", "source"):
            if key in result and result[key] is None:
                result.pop(key)
        return result


class Appearance(_VisualModel):
    age_years: Annotated[StrictInt, Field(ge=0, le=100000)] | None = None
    hair: str = Field(default="", max_length=160)
    eyes: str = Field(default="", max_length=100)
    build: str = Field(default="", max_length=160)
    features: str = Field(default="", max_length=400)


class Garment(_VisualModel):
    category: Literal["clothing", "armor", "accessory"] = Field(
        default="clothing",
        description="Accessories (e.g. necklaces, rings) never hide lower clothing across a whole body region. Armor is a visual category, not a grant of combat stats.",
    )
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
    attachment_slot: BodySlot | None = None
    source: WearSource | None = None

    @model_validator(mode="after")
    def coherent(self) -> "WornItem":
        if self.attachment_slot and self.uncovered_regions:
            raise ValueError("Body placement cannot carry clothing displacement.")
        return self

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
    body: BodyLayout | None = None

    @field_validator("worn")
    @classmethod
    def unique_items(cls, value: list[WornItem]) -> list[WornItem]:
        if len(value) != len({item.item_id for item in value}):
            raise ValueError("A garment can only be worn once.")
        return value
