"""Host-issued operation identity, never a callable capability or model argument."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CommandProof(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(min_length=1, max_length=100)
    actor_id: str = Field(min_length=1, max_length=100)
    operation: Literal["change_item_state", "use_item"]
