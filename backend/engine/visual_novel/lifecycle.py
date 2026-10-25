"""Keep private social provenance local when a saved session is copied or imported."""

from collections.abc import Callable
from copy import deepcopy

from pydantic import ValidationError

from backend.engine.scene_illustrations.snapshots import REGISTRY_KEY, remap_illustrations
from backend.engine.visual_novel.schema import STATE_KEY, SocialState
from backend.engine.visual_novel.state import social_event_id


def remap_social_state(entity_states: dict | None, message_ids: dict[str, str]) -> dict:
    """Remap only schema-defined references, never prose or other engine registries.

    Unsupported state is preserved for a compatible reader. Orphaned provenance is
    discarded, while canonical feelings, goals and identity remain unchanged.
    """
    result = deepcopy(entity_states or {})
    if STATE_KEY not in result:
        return result
    try:
        social = SocialState.model_validate(result[STATE_KEY])
    except (ValidationError, TypeError):
        return result
    social.processed_message_ids = [
        message_ids[old] for old in social.processed_message_ids if old in message_ids
    ]
    for npc_id, character in social.characters.items():
        character.last_source_message_id = message_ids.get(character.last_source_message_id, "")
        character.memories = [
            memory for memory in character.memories if memory.source_message_id in message_ids
        ]
        for memory in character.memories:
            memory.source_message_id = message_ids[memory.source_message_id]
            memory.event_id = social_event_id(memory.source_message_id, npc_id, memory.kind)
    result[STATE_KEY] = social.model_dump(mode="json")
    return result


def copy_vn_state(
    entity_states: dict | None,
    message_ids: dict[str, str],
    copy_asset: Callable[[str | None], str | None],
) -> dict:
    """Rebind VN provenance and give the copied session its own illustration assets."""
    result = remap_illustrations(remap_social_state(entity_states, message_ids), message_ids)
    illustrations = result.get(REGISTRY_KEY, {})
    if isinstance(illustrations, dict) and isinstance(illustrations.get("images"), dict):
        for illustration in illustrations["images"].values():
            if isinstance(illustration, dict):
                illustration["image_url"] = copy_asset(illustration.get("image_url"))
    return result
