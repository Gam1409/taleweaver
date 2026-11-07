"""Explicit player relocation for repairing a session, without simulating travel."""

import shlex
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.session_state import SessionState
from backend.models.world_entity import WorldScene


async def debug_move_player(
    db: AsyncSession,
    state: SessionState,
    args: str,
    user: Any = None,
    adventure: Any = None,
    avatar: Any = None,
) -> str:
    if not state.is_debug_enabled:
        return "DEBUG ERROR: Enable debug mode first."
    try:
        parts = shlex.split(args)
    except ValueError:
        parts = []
    if len(parts) != 2:
        return 'DEBUG ERROR: Usage: /debug move_player "SCENE_ID"'
    scene = await db.scalar(
        select(WorldScene).where(
            WorldScene.session_id == state.session_id,
            WorldScene.id == parts[1],
        )
    )
    if scene is None:
        return "DEBUG ERROR: Destination does not belong to this session."
    if scene.id == state.current_scene_id:
        return "DEBUG: The player is already in this location."
    state.current_scene_id = scene.id
    state.discovered_scenes = list(dict.fromkeys([*(state.discovered_scenes or []), scene.id]))
    states = dict(state.entity_states or {})
    states.pop("__scene_staging__", None)
    state.entity_states = states
    return (
        f"DEBUG: Moved player to {scene.label or scene.id} [{scene.id}]. "
        "NPC locations, inventory and story time are unchanged."
    )
