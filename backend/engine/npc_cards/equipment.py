"""Visible equipment plus source-confirmed displaced wear and body attachments."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.clothing.equipment_view import display_slots
from backend.engine.clothing.profiles import (
    attachment_item_allowed,
    garment_for_item,
    load_profile,
    owned_items,
)
from backend.engine.clothing.visuals import detailed_for_state
from backend.engine.clothing.wear_provenance import source_matches
from backend.engine.debug_transcript import not_debug_sql
from backend.engine.physical_conditions.item_state import project as item_states
from backend.models.chat import ChatMessage


def _item_row(actor: dict, identifier: str, objects: list, states: dict, **fields: Any) -> dict:
    items = owned_items(actor["resolved_inventory"])
    item = items[identifier]
    source = next(
        (row for row in objects if row.entity_type == "OBJECT" and row.id == identifier), None
    )
    override = states.get(identifier) or {}
    if not isinstance(override, dict):
        override = {}
    slots = override.get(
        "wearable_slots", source.wearable_slots if source else item.get("wearable_slots")
    )
    garment = garment_for_item(item)
    current_state = item_states([item], states)[0].get("current_state")
    return {
        "item_id": identifier,
        "name": str(item.get("name") or "")[:200],
        "image_url": override.get(
            "image_url", source.image_url if source else item.get("image_url")
        ),
        "description": garment.description if garment else "",
        "layer": garment.layer if garment else 0,
        "slots": display_slots(slots, list(garment.coverage) if garment else []),
        "visible_regions": [],
        "uncovered_regions": [],
        **({"current_state": current_state} if current_state else {}),
        **fields,
    }


async def equipment_rows(
    db: AsyncSession, state: Any, actor: dict, objects: list, visual: dict | None
) -> list[dict]:
    profile = load_profile(actor["visual_profile"])
    if profile is None:
        return []
    worn = {row.item_id: row for row in profile.worn}
    result = {
        row["item_id"]: _item_row(
            actor,
            row["item_id"],
            objects,
            state.entity_states or {},
            **{
                **{key: value for key, value in row.items() if key != "item_id"},
                "uncovered_regions": worn[row["item_id"]].uncovered_regions
                if row["item_id"] in worn
                else [],
            },
        )
        for row in (visual or {}).get("clothing", [])
    }
    items = owned_items(actor["resolved_inventory"])
    extra = [
        row
        for row in profile.worn
        if row.item_id in items
        and row.item_id not in result
        and (row.attachment_slot or row.uncovered_regions)
        and row.source is not None
    ]
    ids = {
        row.source.source_message_id for row in extra if row.source and row.source.source_message_id
    }
    messages = (
        (
            await db.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == state.session_id,
                    ChatMessage.role.in_(["assistant", "user"]),
                    not_debug_sql(),
                    ChatMessage.id.in_(ids),
                )
            )
        ).all()
        if ids
        else []
    )
    sources = {message.id: message for message in messages}
    for row in extra:
        source = row.source
        message = sources.get(source.source_message_id or "") if source else None
        if (
            source is None
            or message is None
            or message.role != source.source_role
            or not source_matches(source.model_dump(), message.content)
        ):
            continue
        age = profile.appearance.age_years
        adult = type(age) is int and age >= 18
        garment = garment_for_item(items[row.item_id])
        if row.attachment_slot and not attachment_item_allowed(items[row.item_id]):
            continue
        if not row.attachment_slot and (
            garment is None or not set(row.uncovered_regions).issubset(garment.coverage)
        ):
            continue
        if (row.attachment_slot and not adult) or (
            garment and garment.underwear and not (adult and detailed_for_state(state))
        ):
            continue
        allowed = profile.body.attachment_slots if profile.body else None
        if row.attachment_slot and allowed is not None and row.attachment_slot not in allowed:
            continue
        result[row.item_id] = _item_row(
            actor,
            row.item_id,
            objects,
            state.entity_states or {},
            uncovered_regions=row.uncovered_regions,
            description=garment.description if garment and detailed_for_state(state) else "",
            **(
                {"slots": ["BodyVaginal" if row.attachment_slot == "vaginal" else "BodyAnal"]}
                if row.attachment_slot
                else {}
            ),
        )
    return sorted(result.values(), key=lambda row: -row["layer"])
