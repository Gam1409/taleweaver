"""Observer-local transcript expressions, distinct from authoritative world state."""

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from backend.engine.narrated_movement.outcomes import WithMovementOutcomes, overlaps


class MemoryEntry(WithMovementOutcomes):
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
        if self.action_span and self.kind != "own_action":
            raise ValueError("An action occurrence requires the observer's own action.")
        if self.movement_outcomes and (
            self.kind != "own_action"
            or any(
                entry.actor_id != self.observer_id
                or not (
                    overlaps(entry, self.quote, self.action_span)
                    if self.action_span
                    else entry.evidence in self.quote
                )
                for entry in self.movement_outcomes
            )
        ):
            raise ValueError("Movement outcomes must qualify the observer's own action quote.")
        if self.kind == "own_action" and (
            self.source_role != "assistant" or self.speaker_id != self.observer_id
        ):
            raise ValueError("An own action requires the observer's reviewed assistant narration.")
        return self
