"""VN-only source references; persisted world events retain their existing shape."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from backend.engine.rule_engine import EntityMovement


class MovementSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["previous_narration", "current_player_action"]
    passage_id: str = Field(min_length=1, max_length=40)
    basis: Literal["completed", "resolved_external_effect", "attempt", "intention", "uncertain"]


def optional_source(value: Any) -> MovementSource | None:
    try:
        return MovementSource.model_validate(value) if value is not None else None
    except ValueError:
        return None


SourceReference = Annotated[MovementSource | None, BeforeValidator(optional_source)]


class VnMovement(EntityMovement):
    movement_source: SourceReference = None


INSTRUCTION = """
VN MOVEMENT SOURCES: Every NPC moved_entities entry and NPC presence/spatial_position
update needs movement_source with kind, passage_id and basis. Copy a supplied
history:pN or player:pN reference from movement_sources; offsets are host-owned.
previous_narration + completed requests revalidation of a missed completed movement
from that exact latest assistant source. Old prose alone is not confirmation:
the movement owner rechecks its source, route and prior outcome. Unconfirmed may be
resolved by that check; a previously blocked movement cannot become past success.
current_player_action + resolved_external_effect is only a resolved physical effect
of the player's CURRENT action (for example carrying, pushing or transport), not a
request for an NPC's voluntary cooperation. Merely quoting a request proves no force
or success. Mark attempts, wishes and uncertain effects accordingly; they cannot move
anyone. Respect current world capabilities and access. Fresh voluntary NPC initiative
belongs to story_beat or the active NPC planner, never an invented player effect.
Missing/invalid proof preserves canonical location and presence for review. Other
independent world updates retain their existing checks. Do not put an unconfirmed
departure into notes or scene orientation as an established fact.
"""
