"""Recovery wire shapes expose identity exclusivity to structured-output models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from backend.engine.clothing.schema import Garment, Region
from backend.engine.narrated_items.schema import ItemAction, NewItem
from backend.schemas.authoring_completion import EquipmentSlot


class ExistingRecoveryAction(ItemAction):
    attachment_slot: None = None
    uncovered_regions: None = None  # Recovery placement belongs to the outer entry.
    item_id: str = Field(
        min_length=1,
        max_length=100,
        description="Exact ID from canonical_items. Never invent an ID for a missing garment.",
    )
    new_item: None = Field(default=None, description="Must be null for an existing item.")


class RecoveryGarment(NewItem):
    kind: Literal["clothing"] = "clothing"
    clothing: Garment
    wearable_slots: list[EquipmentSlot] = Field(min_length=1, max_length=4)


class NewRecoveryAction(ItemAction):
    attachment_slot: None = None
    uncovered_regions: None = None
    item_id: None = Field(default=None, description="Must be null. The engine assigns new IDs.")
    new_item: RecoveryGarment = Field(
        description="Evidence-backed description of the missing garment."
    )


class RecoveryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_message_id: str
    action: ExistingRecoveryAction | NewRecoveryAction
    uncovered_regions: list[Region] = Field(default_factory=list, max_length=7)
    placement_evidence: str = Field(default="", max_length=800)
    restore_coverage: StrictBool = Field(
        default=False,
        description="Explicit return to normal garment coverage. Requires worn disposition, no uncovered regions and an exact restoring placement quote. Omission never resets placement.",
    )

    @field_validator("action", mode="before")
    @classmethod
    def action_data(cls, value: object) -> object:
        # Internal callers can still supply a validated live action; revalidate its wire shape.
        return value.model_dump() if isinstance(value, ItemAction) else value


class OmittedMention(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["underwear_bottom", "underwear_top"]
    reason: str = Field(min_length=4, max_length=240)
    source_message_id: str
    evidence: str = Field(min_length=4, max_length=800)


class RecoveryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[RecoveryEntry] = Field(default_factory=list, max_length=16)
    notes: str = Field(default="", max_length=1200)
    omitted_mentions: list[OmittedMention] = Field(default_factory=list, max_length=4)
