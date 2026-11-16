"""Restore source references after imported messages receive their local IDs."""

from typing import Any

from backend.engine.chpm.lifecycle import fork
from backend.engine.clothing.wear_provenance import remap_profile
from backend.engine.living_world.portability import remap_intentions
from backend.engine.memory_rag.lifecycle import restore_memory
from backend.engine.physical_conditions.ledger import remap
from backend.engine.scene_illustrations.snapshots import remap_illustrations
from backend.engine.visual_novel.lifecycle import remap_social_state


def restore_sources(avatar: Any, state: Any, raw_state: dict, message_ids: dict[str, str]) -> None:
    state.living_world = remap_intentions(getattr(state, "living_world", None), message_ids)
    avatar.visual_profile = remap_profile(avatar.visual_profile, message_ids)
    restore_memory(state, raw_state, message_ids)
    state.entity_states = fork(
        remap_illustrations(
            remap_social_state(remap(state.entity_states, message_ids), message_ids), message_ids
        ),
        message_ids,
        state.session_id,
    )
