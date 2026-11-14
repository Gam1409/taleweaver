"""Observer-local transcript expressions, distinct from authoritative world state."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MemoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_message_id: str
    source_revision_id: str | None = None
    source_hash: str
    source_role: Literal["user", "assistant"]
    scene_id: str
    observer_id: str
    speaker_id: str
    kind: Literal["player_observation", "own_speech", "heard_speech", "own_action"]
    quote: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def own_action_only(self) -> "MemoryEntry":
        if self.kind == "own_action" and (
            self.source_role != "assistant" or self.speaker_id != self.observer_id
        ):
            raise ValueError("An own action requires the observer's reviewed assistant narration.")
        return self
