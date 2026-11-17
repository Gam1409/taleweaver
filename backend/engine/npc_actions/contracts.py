"""Operation-specific request shapes with no model-supplied actor/session authority."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.engine.clothing.schema import Region
from backend.engine.physical_conditions.schema import ITEM_PART_PATTERN

Identifier = Annotated[str, Field(min_length=1, max_length=100)]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    tool: str


class Move(Request):
    tool: Literal["move_to"]
    destination_scene_id: Identifier


class Item(Request):
    item_id: Identifier


class Take(Item):
    tool: Literal["take_item"]


class PutDown(Item):
    tool: Literal["put_down_item"]
    position: str | None = Field(default=None, min_length=1, max_length=120)


class Give(Item):
    tool: Literal["give_item"]
    recipient_id: Identifier


class Wear(Item):
    tool: Literal["wear_item"]


class TakeOff(Item):
    tool: Literal["take_off_item"]


class Adjust(Item):
    tool: Literal["adjust_clothing"]
    uncovered_regions: list[Region] = Field(max_length=7)

    @field_validator("uncovered_regions")
    @classmethod
    def unique_regions(cls, value: list[Region]) -> list[Region]:
        if len(value) != len(set(value)):
            raise ValueError("Supply each final uncovered region once.")
        return value


class ChangeState(Item):
    tool: Literal["change_item_state"]
    dimension: str = Field(min_length=1, max_length=80, pattern=ITEM_PART_PATTERN)
    detail: str = Field(min_length=1, max_length=320)
    visibility: Literal["public", "private"] = "public"


class Use(Item):
    tool: Literal["use_item"]
    extent: Literal["partial", "full"]
    remaining_detail: str | None = Field(default=None, min_length=1, max_length=320)


class Discard(Request):
    tool: Literal["discard_actions"]


ActionRequest = Annotated[
    Move | Take | PutDown | Give | Wear | TakeOff | Adjust | ChangeState | Use | Discard,
    Field(discriminator="tool"),
]

ACTION_MODELS: dict[str, type[Request]] = {
    "move_to": Move,
    "take_item": Take,
    "put_down_item": PutDown,
    "give_item": Give,
    "wear_item": Wear,
    "take_off_item": TakeOff,
    "adjust_clothing": Adjust,
    "change_item_state": ChangeState,
    "use_item": Use,
    "discard_actions": Discard,
}
