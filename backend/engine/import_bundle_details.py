"""Rebind legacy save history and materialize a session-owned copy of its world."""

from copy import deepcopy
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.chpm.lifecycle import fork as fork_chpm
from backend.engine.living_world.portability import remap_intentions
from backend.engine.memory_rag.lifecycle import restore_memory
from backend.engine.npc_journal.messages import restore_messages
from backend.engine.scene_illustrations.snapshots import remap_illustrations
from backend.engine.visual_novel.lifecycle import remap_social_state
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from backend.models.world_map import WorldMap

STATE_FIELDS = (
    "max_memory_turns",
    "time_system",
    "time_config",
    "quests",
    "start_datetime",
    "plot",
    "rules",
    "walkthrough",
    "completed_condition",
    "gameover_condition",
    "completed_guard_expression",
    "gameover_guard_expression",
    "active_sequence_id",
    "active_sequence_order",
    "tts_director_notes",
    "selected_image_styles",
    "selected_tone",
    "is_completed",
    "is_debug_enabled",
    "is_walkthrough_revealed",
    "allow_dynamic_items",
)
_SYSTEM_FIELDS = {"pk", "session_id", "template_id", "created_at", "updated_at"}


def restore_details(
    db: AsyncSession, state: SessionState, old_state: dict, history: list[dict]
) -> None:
    for field in STATE_FIELDS:
        if field in old_state:
            setattr(state, field, deepcopy(old_state[field]))
    ids = restore_messages(db, state.session_id, history)
    state.living_world = remap_intentions(state.living_world, ids)
    restore_memory(state, old_state, ids)
    state.entity_states = fork_chpm(
        remap_illustrations(remap_social_state(state.entity_states, ids), ids),
        ids,
        state.session_id,
    )


def _values(model: Any, raw: dict) -> dict:
    return {
        column.name: deepcopy(raw[column.name])
        for column in model.__table__.columns
        if column.name not in _SYSTEM_FIELDS and column.name in raw
    }


async def _records(db: AsyncSession, model: Any, template_id: str, raw: Any) -> list[dict]:
    if raw:
        if not isinstance(raw, list) or any(not isinstance(row, dict) for row in raw):
            raise ValueError("Legacy world records must be a list of objects.")
        return raw
    rows = await db.scalars(
        select(model).where(model.template_id == template_id, model.session_id.is_(None))
    )
    return [
        {column.name: deepcopy(getattr(row, column.name)) for column in model.__table__.columns}
        for row in rows
    ]


async def restore_world(
    db: AsyncSession, state: SessionState, template_id: str, payload: dict
) -> None:
    exit_ids = {}
    for model, key in ((WorldScene, "scenes"), (WorldExit, "exits"), (WorldEntity, "entities")):
        records = await _records(db, model, template_id, payload.get(key))
        exit_ids.update(_restore_records(db, model, records, state))
    state.exit_states = {
        exit_ids.get(key, key): value for key, value in (state.exit_states or {}).items()
    }
    world = payload.get("world_map")
    if world is not None:
        if not isinstance(world, dict):
            raise ValueError("Legacy world map must be an object.")
        db.add(
            WorldMap(
                session_id=state.session_id,
                nodes=deepcopy(world.get("nodes") or {}),
                edges=deepcopy(world.get("edges") or []),
                current_scene_id=state.current_scene_id,
            )
        )


def _restore_records(
    db: AsyncSession, model: Any, records: list[dict], state: SessionState
) -> dict:
    exit_ids = {}
    for raw in records:
        values = _values(model, raw)
        _normalize(model, values, raw, state.current_scene_id)
        if model is WorldExit:
            new_id = str(uuid4())
            exit_ids[raw.get("id") or new_id] = new_id
            values["id"] = new_id
        db.add(model(**values, template_id=None, session_id=state.session_id))
    return exit_ids


def _normalize(model: Any, values: dict, raw: dict, scene: str) -> None:
    if model is WorldScene:
        values.setdefault("label", raw.get("name") or "Unknown scene")
        values.setdefault("description", "")
    if model is WorldEntity:
        values.setdefault("current_scene_id", raw.get("start_scene_id") or scene)
        values.setdefault("description", "")
