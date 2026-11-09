"""Bounded chronological evidence and state fingerprints for explicit wardrobe recovery."""

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from backend.engine.character_identity import identity_facts
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.history import load_history
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.models.world_entity import WorldEntity

KEY = "__wardrobe_recovery__"


async def recovery_context(db: Any, state: Any, avatar: Any, npc_id: str) -> dict:
    entities = list(
        await db.scalars(select(WorldEntity).where(WorldEntity.session_id == state.session_id))
    )
    npc = next((row for row in entities if row.id == npc_id and row.entity_type == "NPC"), None)
    if npc is None:
        raise ValueError("NPC does not belong to this session.")
    history = await load_history(db, state.session_id)
    messages = history.messages
    states = deepcopy(state.entity_states or {})
    states.pop(KEY, None)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "states": states,
                "scene": state.current_scene_id,
                "avatar": {
                    "inventory": avatar.inventory,
                    "equipment": avatar.equipment,
                    "visual_profile": avatar.visual_profile,
                },
                "entities": [
                    {
                        "id": row.id,
                        "name": row.name,
                        "description": row.description,
                        "inventory": row.inventory,
                        "metadata": row.metadata_json,
                        "scene": row.current_scene_id,
                        "age": row.age_years,
                        "visual_profile": row.visual_profile,
                    }
                    for row in sorted(entities, key=lambda row: row.id)
                ],
                "messages": messages,
                "message_revisions": history.revisions,
            },
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        ).encode()
    ).hexdigest()
    # Explicit debug recovery can inspect an absent NPC, but may only change that NPC's own garments.
    override = states.get(npc.id, {})
    states[npc.id] = {**override, "is_hidden": False, "is_defeated": False, "presence": "present"}
    proxy = SimpleNamespace(
        avatar=avatar,
        state=SimpleNamespace(
            session_id=state.session_id,
            entity_states=states,
            current_scene_id=override.get("current_scene_id", npc.current_scene_id),
        ),
    )
    actor = actor_records(proxy, entities)[npc.id]
    actor.update(identity_facts(npc))
    snapshot = possession_snapshot(proxy, entities)
    return {
        "actor": actor,
        "snapshot": snapshot,
        "messages": messages,
        "fingerprint": fingerprint,
        "limited": history.limited,
    }
