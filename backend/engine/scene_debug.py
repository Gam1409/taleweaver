"""Read saved scene evidence without extracting facts, rebuilding plans or invoking models."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.scene_illustrations.context import plan_enabled
from backend.engine.scene_illustrations.snapshots import content_hash, registry_of
from backend.engine.scene_staging import props
from backend.engine.scene_staging.state import KEY as STAGING_KEY
from backend.engine.scene_staging.state import digest
from backend.engine.visual_novel.config import read_settings
from backend.engine.visual_novel.presentation import session_mode
from backend.engine.visual_plan_lifecycle import KEY as PLAN_KEY
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldScene


def snapshot_status(snapshot: Any, message: ChatMessage) -> str:
    if not isinstance(snapshot, dict) or not snapshot:
        return "missing"
    return "matches_message" if snapshot.get("content_hash") == content_hash(message) else "stale"


def staging_status(state: SessionState, staging: dict, latest: ChatMessage | None) -> str:
    if not read_settings(state).scene_staging:
        return "disabled"
    if not staging:
        return "not_recorded"
    if latest is None or staging.get("scene_id") != state.current_scene_id:
        return "stale"
    if (
        staging.get("source_hash") != digest(latest.content)
        or latest.scene_id != state.current_scene_id
        or staging.get("source_message_id", latest.id) != latest.id
        or staging.get("source_revision_id", latest.revision_id) != latest.revision_id
    ):
        return "stale"
    return str(staging.get("status") or "unconfirmed")


def _message_info(message: ChatMessage, snapshots: dict) -> dict:
    return {
        "id": message.id,
        "scene_id": message.scene_id,
        "revision_id": message.revision_id,
        "created_at": message.created_at.isoformat(),
        "excerpt": message.content[:120],
        "snapshot_status": snapshot_status(snapshots.get(message.id), message),
    }


async def scene_debug_payload(
    db: AsyncSession, state: SessionState, selected: ChatMessage | None, recent: list[ChatMessage]
) -> dict:
    states = state.entity_states or {}
    snapshots = registry_of(states)["snapshots"]
    staging = states.get(STAGING_KEY) or {}
    staging = staging if isinstance(staging, dict) else {}
    scene = await db.scalar(
        select(WorldScene).where(
            WorldScene.session_id == state.session_id, WorldScene.id == state.current_scene_id
        )
    )
    cache = states.get(PLAN_KEY) or {}
    entries = cache.get("entries", {}) if isinstance(cache, dict) else {}
    plans = [
        {"cache_key": key, "data": value}
        for key, value in entries.items()
        if selected and isinstance(value, dict) and value.get("message_id") == selected.id
    ]
    settings = read_settings(state)
    return {
        "session_id": state.session_id,
        "mode": await session_mode(db, state),
        "settings": settings.model_dump(),
        "current_scene": None
        if scene is None
        else {
            "id": scene.id,
            "label": scene.label,
            "description": scene.description,
            "decorative_objects": scene.decorative_objects,
        },
        "current_scene_id": state.current_scene_id,
        "staging_status": staging_status(state, staging, recent[0] if recent else None),
        "staging": staging or None,
        "props": states.get(props.KEY),
        "messages": [_message_info(message, snapshots) for message in recent],
        "selected_message": _message_info(selected, snapshots) if selected else None,
        "snapshot": snapshots.get(selected.id) if selected else None,
        "plan_route_enabled": await plan_enabled(db, state),
        "cached_plans": plans,
        "limits": {"message_list": 100, "snapshot_retention": 100, "plan_cache_entries": 8},
    }
