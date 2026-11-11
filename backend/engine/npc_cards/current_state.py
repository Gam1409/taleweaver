"""Read-only NPC card projection using the existing clothing and surface visibility rules."""

from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.text_evidence import require_span
from backend.engine.character_identity import identity_profile
from backend.engine.clothing.context import resolved_inventory
from backend.engine.clothing.profiles import garment_for_item, load_profile, owned_items
from backend.engine.clothing.projection import visible_character
from backend.engine.clothing.visuals import detailed_for_state, session_objects
from backend.engine.npc_presence import physically_present
from backend.engine.physical_conditions.ledger import read
from backend.engine.physical_conditions.schema import Condition
from backend.engine.physical_conditions.visuals import project
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity


def _clothes(actor: dict, objects: list, states: dict, visual: dict) -> list[dict]:
    items = owned_items(actor["resolved_inventory"])
    sources = {item.id: item for item in objects}
    profile = load_profile(actor["visual_profile"])
    placements = {item.item_id: item.uncovered_regions for item in profile.worn} if profile else {}
    result = []
    for row in visual["clothing"]:
        identifier = row["item_id"]
        item = items[identifier]
        garment = garment_for_item(item)
        source = sources.get(identifier)
        override = states.get(identifier) or {}
        image = override.get("image_url", source.image_url if source else item.get("image_url"))
        result.append(
            {
                **row,
                "image_url": image,
                "layer": garment.layer if garment else 0,
                "uncovered_regions": placements.get(identifier, []),
            }
        )
    return sorted(result, key=lambda row: -row["layer"])


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
    # Public states disclosed in completed narration remain known when covered.
    # Recheck the original fragment rather than exposing a private ledger description.
    candidates = [
        row
        for row in ledger.conditions.values()
        if row.status != "resolved"
        and row.visibility == "public"
        and row.target_id in {actor["id"], *names}
        and row.id not in by_id
        and row.latest.kind == "narration"
    ]
    messages = (
        (
            await db.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == state.session_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.id.in_({row.latest.message_id for row in candidates}),
                )
            )
        ).all()
        if candidates
        else []
    )
    sources = {message.id: message.content for message in messages}
    for row in candidates:
        quote = _source_quote(row, sources)
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
    result["conditions"] = await _conditions(db, state, actor, detailed, visual)
    if visual is None:
        return result
    result["clothing"] = {
        "status": "available",
        "detail_limited": visual["clothing_detail_limited"],
        "items": _clothes(actor, objects, states, visual),
    }
    return result
