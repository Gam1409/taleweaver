"""Recovery wire shapes expose identity exclusivity to structured-output models."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.engine.clothing.schema import Region
from backend.engine.narrated_items.schema import ItemAction, NewItem


class ExistingRecoveryAction(ItemAction):
    item_id: str = Field(
        min_length=1,
        max_length=100,
        description="Exact ID from canonical_items. Never invent an ID for a missing garment.",
    )
    new_item: None = Field(default=None, description="Must be null for an existing item.")


class NewRecoveryAction(ItemAction):
    item_id: None = Field(default=None, description="Must be null. The engine assigns new IDs.")
    new_item: NewItem = Field(description="Evidence-backed description of the missing garment.")


class RecoveryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_message_id: str
    action: ExistingRecoveryAction | NewRecoveryAction
    uncovered_regions: list[Region] = Field(default_factory=list, max_length=7)
    placement_evidence: str = Field(default="", max_length=800)

    @field_validator("action", mode="before")
    @classmethod
    def action_data(cls, value: object) -> object:
        # Internal callers can still supply a validated live action; revalidate its wire shape.
        return value.model_dump() if isinstance(value, ItemAction) else value


class RecoveryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[RecoveryEntry] = Field(default_factory=list, max_length=16)
    notes: str = Field(default="", max_length=1200)
