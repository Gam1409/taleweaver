"""Read-only NPC card projection using the existing clothing and surface visibility rules."""

from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.text_evidence import require_span
from backend.engine.character_identity import identity_profile
from backend.engine.clothing.context import resolved_inventory
from backend.engine.clothing.equipment_view import layout
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.projection import visible_character
from backend.engine.clothing.visuals import detailed_for_state, session_objects
from backend.engine.npc_cards.equipment import equipment_rows
from backend.engine.npc_presence import physically_present
from backend.engine.physical_conditions.ledger import read
from backend.engine.physical_conditions.schema import Condition
from backend.engine.physical_conditions.visuals import project
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity


def _source_quote(row: Condition, messages: dict[str, str]) -> str:
    source = row.latest
    text = messages.get(source.message_id or "", "")
    if (
        source.kind != "narration"
        or not text
        or source.quote not in text
        or sha256(text.encode()).hexdigest() != source.content_hash
    ):
        return ""
    try:
        require_span(text, source.quote, source.evidence_span)
    except ValueError:
        return ""
    return source.quote


async def _conditions(
    db: AsyncSession,
    state: SessionState,
    actor: dict,
    detailed: bool,
    clothing: dict | None,
) -> dict:
    try:
        ledger = read(state.entity_states)
    except ValueError:
        return {"status": "unavailable", "items": []}
    visible = project(state, {actor["id"]: actor}, detailed=detailed, limit=None)
    by_id = {row["id"]: {**row, "observation": "visible"} for row in visible}
    names = {row["item_id"]: row["name"] for row in (clothing or {}).get("clothing", [])}
    # Public facts remain known when covered. Explicit public Debug corrections
    # use their chosen detail; narrated facts must still match their original source.
    candidates = [
        row
        for row in ledger.conditions.values()
        if row.status != "resolved"
        and row.visibility == "public"
        and row.target_id in {actor["id"], *names}
        and row.id not in by_id
        and row.latest.kind in {"narration", "manual"}
    ]
    message_ids = {row.latest.message_id for row in candidates if row.latest.kind == "narration"}
    messages = (
        (
            await db.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == state.session_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.is_debug.is_(False),
                    ChatMessage.id.in_(message_ids),
                )
            )
        ).all()
        if message_ids
        else []
    )
    sources = {message.id: message.content for message in messages}
    for row in candidates:
        quote = row.detail if row.latest.kind == "manual" else _source_quote(row, sources)
        if quote:
            by_id[row.id] = {
                "id": row.id,
                "target_id": row.target_id,
                "target_name": names.get(row.target_id),
                "detail": quote,
                "status": row.status,
                "observation": "recorded",
            }
    return {
        "status": "available" if by_id or load_profile(actor["visual_profile"]) else "unavailable",
        "items": [
            {
                **row,
                "kind": ledger.conditions[row["id"]].kind,
                "part": ledger.conditions[row["id"]].part,
                "last_changed_minute": ledger.conditions[row["id"]].last_changed_minute,
            }
            for row in by_id.values()
        ],
    }


async def character_current_state(
    db: AsyncSession,
    state: SessionState,
    npc: WorldEntity,
) -> dict[str, Any]:
    """Only physically present, visible NPCs have a current observable snapshot."""
    states = state.entity_states or {}
    override = states.get(npc.id) or {}
    if not isinstance(override, dict):
        override = {}
    result: dict[str, Any] = {
        "layout": layout(
            override.get("visual_profile", npc.visual_profile),
            gender=npc.gender,
            npc_type=npc.npc_type,
        ),
        "availability": "not_present",
        "game_minute": state.in_game_time,
        "clothing": {"status": "unavailable", "items": [], "detail_limited": True},
        "conditions": {"status": "unavailable", "items": []},
    }
    if (
        override.get("is_hidden", npc.is_hidden)
        or override.get("current_scene_id", npc.current_scene_id) != state.current_scene_id
        or not physically_present(npc, state)
    ):
        return result
    result["availability"] = "present"
    objects = await session_objects(db, state.session_id)
    inventory = (
        override.get("inventory", npc.inventory or (npc.metadata_json or {}).get("inventory", []))
        or []
    )
    actor = {
        "id": npc.id,
        "visual_profile": identity_profile(npc, override.get("visual_profile", npc.visual_profile)),
        "resolved_inventory": resolved_inventory(inventory, objects, states),
    }
    detailed = detailed_for_state(state)
    visual = visible_character(
        actor["visual_profile"], actor["resolved_inventory"], detailed=detailed
    )
    if visual is None:
        result["conditions"] = await _conditions(db, state, actor, detailed, visual)
        return result
    clothes = await equipment_rows(db, state, actor, objects, visual)
    result["conditions"] = await _conditions(db, state, actor, detailed, {"clothing": clothes})
    result["clothing"] = {
        "status": "available",
        "detail_limited": visual["clothing_detail_limited"],
        "items": clothes,
    }
    return result
