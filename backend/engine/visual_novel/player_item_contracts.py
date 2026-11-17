"""Source-attributed preliminary item proposals; execution stays with canonical owners."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

MAX_ACTIONS = 6


def operation_rules(schema: dict) -> None:
    """Expose the existing identity validator to the model's structured decoder."""
    operations = schema["properties"]["operation"]["enum"]
    schema["oneOf"] = [
        {
            "properties": {
                "operation": {"enum": [op for op in operations if op != "acquire_garment"]},
                "item_id": {"type": "string"},
                "creation_ref": {"type": "null"},
            },
            "required": ["item_id"],
        },
        {
            "properties": {
                "operation": {"const": "acquire_garment"},
                "item_id": {"type": "null"},
                "creation_ref": {"type": "integer"},
            },
            "required": ["creation_ref"],
        },
    ]


class PlayerItemAction(BaseModel):
    """An attributed proposal; only the player owner's validated subset may execute."""

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=False, json_schema_extra=operation_rules
    )

    performer_id: str | None = Field(
        min_length=1,
        max_length=100,
        description="Actual performer ID from the supplied player executor or present characters; null when unresolved. This is distinct from the recipient or wardrobe target.",
    )
    operation: Literal[
        "take", "give", "drop", "consume", "destroy", "wear", "remove", "adjust", "acquire_garment"
    ]
    item_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Exact existing item ID being handled; required except acquire_garment. The recipient belongs in target_id.",
    )
    passage_id: str = Field(min_length=1, max_length=40)
    basis: Literal["performed", "attempt", "intention", "uncertain"]
    target_id: str | None = Field(
        default=None,
        max_length=100,
        description="Recipient/container ID for give, or actor ID for wardrobe operations; null for take/drop/consume/destroy. This is distinct from item_id.",
    )
    creation_ref: StrictInt | None = Field(default=None, ge=0, le=2)

    @model_validator(mode="after")
    def identity(self) -> "PlayerItemAction":
        creation = self.operation == "acquire_garment"
        if creation != (self.creation_ref is not None) or creation == (self.item_id is not None):
            raise ValueError("Use an existing item ID, or one supplied garment creation reference.")
        return self
