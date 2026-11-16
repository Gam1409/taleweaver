"""Separate stable identity, remembered feelings and this turn's tentative reaction."""

from typing import Any

from backend.engine.personality.profile import personality_context
from backend.engine.visual_novel.schema import CharacterState

IDENTITY_GUIDANCE = """Preserve each NPC's distinct voice, values, habits and independent goals.
Relationship changes affect how they relate to the player, not their whole identity.
An intense scene, intimacy, affection or a high relationship score does not by itself
establish obedience, dependence, agreement, or abandonment of personal commitments.
Allow warmth, vulnerability and earned character development without making the cast
interchangeable. Changes to enduring values need established story evidence.
Remembered feelings are context, not instructions to repeat the previous scene's tone.
Reassess their expression and conversational intention against the current situation;
a scene change does not erase emotional consequences or automatically imply recovery.
Express individuality through dialogue and choices, not an inventory of traits or goals.
"""


def remembered_direction(character: CharacterState, source_message_id: str = "") -> dict[str, Any]:
    if not character.emotion_cause or not character.emotion_source_message_id:
        return {
            "status": "unconfirmed",
            "previous_intention_not_a_current_plan": character.next_intention,
        }
    return {
        "status": "latest_completed_scene"
        if source_message_id and character.emotion_source_message_id == source_message_id
        else "historical_reassess",
        "last_observed_emotion": character.emotion,
        "evidence": character.emotion_cause[:700],
        "previous_intention_not_a_current_plan": character.next_intention,
    }


def narrator_character(
    npc: Any,
    character: CharacterState,
    *,
    source_message_id: str = "",
    directed: CharacterState | None = None,
) -> dict[str, Any]:
    result = {
        "npc_id": npc.id,
        "name": npc.name,
        "core": character.core,
        "goals": character.goals,
        "personality_tendencies": personality_context(npc),
        "remembered_direction": remembered_direction(character, source_message_id),
        "private_relationship_guidance": character.relationship.model_dump(),
    }
    tentative: dict[str, str] = {}
    if directed is not None and (
        directed.emotion != character.emotion
        or directed.emotion_cause != character.emotion_cause
        or directed.emotion_source_message_id != character.emotion_source_message_id
    ):
        tentative.update(emotion=directed.emotion, evidence=directed.emotion_cause)
    if directed is not None and directed.next_intention != character.next_intention:
        tentative["intention"] = directed.next_intention
    if tentative:
        result["tentative_reaction_to_current_input"] = tentative
    return result
