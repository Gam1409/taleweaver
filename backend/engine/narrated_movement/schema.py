"""Evidence-backed movement candidates, separate from poses and possessions."""

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from backend.core.text_evidence import WithEvidenceSpan


class MovementProposal(WithEvidenceSpan):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    actor_id: str = Field(min_length=1, max_length=100)
    destination_scene_id: str | None = Field(default=None, min_length=1, max_length=100)
    presence: Literal["present", "audible", "absent"] = "present"
    basis: Literal["completed", "attempt", "intention", "historical", "uncertain"]
    evidence: str = Field(min_length=4, max_length=1000)
    player_evidence: str | None = Field(default=None, min_length=4, max_length=1000)

    @model_validator(mode="after")
    def coherent(self) -> "MovementProposal":
        if self.destination_scene_id is not None and self.presence != "present":
            raise ValueError("Travel records physical presence at its destination.")
        if self.actor_id == "__player__" and (
            self.destination_scene_id is None or not self.player_evidence
        ):
            raise ValueError("Player travel requires a destination and current player evidence.")
        if self.actor_id != "__player__" and self.player_evidence is not None:
            raise ValueError("NPC movements do not claim a player action.")
        return self


INSTRUCTIONS = """
MOVEMENTS: Always return movements explicitly, using [] when none occurred.
Reconcile completed travel and local presence from this completed_narration,
using movement_context's exact actor and destination IDs. A source reference must
describe the actual completed departure or arrival, not an intention, suggestion,
remembered event, quoted story, or emotional withdrawal. Use basis accordingly.
Do not infer that all present NPCs follow: report each explicitly moving actor.
Use destination_scene_id for travel to a supplied map destination. Null is only
for a local presence change within the same map location (outside the immediate
view, still audible, or returned); never use it to bypass a blocked map exit.
Respect can_move and allowed_destinations; never unlock exits or invent locations.
For __player__, the current_player_message must explicitly authorize this immediate
traversal (including an immediate group command). Copy its exact contiguous words
into player_evidence. Narration alone cannot choose the player's travel. Plans,
questions and hypothetical journeys do not authorize it. NPC player_evidence is null.
Already applied travel to the current destination is not a second journey.
Movement belongs to coverage domain scene, independently of scene facts and poses.
When the player changes map location, scene_updates describe the final destination:
use its supplied destination ID for room facts, not the departed scene ID. Cite
completed narration only; the previous room's authored description is not evidence
about the destination. Scene facts cannot move characters by themselves.
"""
