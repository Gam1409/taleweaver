"""Evidence-backed physical placement, independent of canonical inventory ownership."""

from collections import Counter
from collections.abc import Iterable
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def digest(text: str) -> str:
    return sha256(text.encode()).hexdigest()


KEY = "__scene_props__"


class PropDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    item_id: str = Field(min_length=1, max_length=100)
    owner_id: str = Field(min_length=1, max_length=100)
    evidence: str = Field(min_length=3, max_length=800)
    spatial_position: str = Field(default="", max_length=120)
    status: Literal["confirmed", "provisional", "clear"] = "provisional"


def _ids(values: Iterable[Any] | None) -> set[str]:
    return {str(v.get("id")) if isinstance(v, dict) else str(v) for v in values or []}


def candidates(avatar: Any, rows: list[Any], state: Any, cast_ids: set[str]) -> list[dict]:
    result = []
    by_id = {row.id: row for row in rows}
    actors = [avatar, *[row for row in rows if row.id in cast_ids and row.id != avatar.id]]
    for actor in actors:
        result.extend(_actor_items(actor, by_id, state))
    return result


def _actor_items(actor: Any, by_id: dict, state: Any) -> list[dict]:
    result = []
    override = (state.entity_states or {}).get(actor.id, {})
    inventory = override.get("inventory", getattr(actor, "inventory", []) or [])
    profile = override.get("visual_profile", getattr(actor, "visual_profile", None)) or {}
    profile = profile if isinstance(profile, dict) else {}
    worn = {entry.get("item_id") for entry in profile.get("worn", []) if isinstance(entry, dict)}
    equipment = getattr(actor, "equipment", None) or {}
    worn |= _ids(equipment.values())
    items = {str(item.get("id")): item for item in inventory if isinstance(item, dict)}
    for item_id in sorted(_ids(inventory) - worn):
        row = by_id.get(item_id)
        hidden = (
            (state.entity_states or {})
            .get(item_id, {})
            .get("is_hidden", getattr(row, "is_hidden", False))
        )
        if hidden:
            continue
        name = row.name if row else items.get(item_id, {}).get("name")
        if name:
            result.append({"item_id": item_id, "owner_id": actor.id, "name": name})
    return result


def reconcile(
    state: Any,
    narration: str,
    changes: list[PropDelta],
    items: list[dict],
    *,
    valid_items: list[dict] | None = None,
) -> None:
    previous = deepcopy((state.entity_states or {}).get(KEY) or {})
    known = {(item["item_id"], item["owner_id"]): item for item in items}
    eligible = {
        (item["item_id"], item["owner_id"])
        for item in (valid_items if valid_items is not None else items)
    }
    records = [
        entry
        for entry in previous.get("items", [])
        if (entry["item_id"], entry["owner_id"]) in eligible
    ]
    counts = Counter(change.item_id for change in changes)
    seen = set()
    for change in changes:
        key = (change.item_id, change.owner_id)
        valid = (
            key in known
            and counts[change.item_id] == 1
            and key not in seen
            and change.evidence in narration
            and (
                change.status != "confirmed"
                or bool(change.spatial_position and change.spatial_position in change.evidence)
            )
        )
        seen.add(key)
        if not valid:
            continue
        records = [entry for entry in records if entry["item_id"] != change.item_id]
        if change.status == "clear":
            continue
        records.append(
            {
                **known[key],
                "scene_id": state.current_scene_id,
                "status": change.status,
                "spatial_position": change.spatial_position,
                "evidence": change.evidence,
                "source_hash": digest(narration),
            }
        )
    state.entity_states = {**(state.entity_states or {}), KEY: {"items": records}}


def stamp(state: Any, message: Any) -> None:
    data = deepcopy((state.entity_states or {}).get(KEY) or {})
    for entry in data.get("items", []):
        if entry.get("source_hash") == digest(message.content) and not entry.get(
            "source_revision_id"
        ):
            entry.update(
                source_message_id=message.id,
                placed_by_message_id=message.id,
                source_revision_id=message.revision_id,
                extracted_at=datetime.now(timezone.utc).isoformat(),
                confirmed_by="narration_evidence" if entry["status"] == "confirmed" else None,
            )
    if data:
        state.entity_states = {**state.entity_states, KEY: data}


def project(state: Any, items: list[dict]) -> list[dict]:
    known = {(item["item_id"], item["owner_id"]) for item in items}
    return [
        {key: entry[key] for key in ("item_id", "owner_id", "name", "spatial_position")}
        for entry in ((state.entity_states or {}).get(KEY) or {}).get("items", [])
        if entry.get("status") == "confirmed"
        and entry.get("scene_id") == state.current_scene_id
        and (entry["item_id"], entry["owner_id"]) in known
    ]


def retract(state: Any, message_id: str) -> None:
    data = deepcopy((state.entity_states or {}).get(KEY) or {})
    data["items"] = [
        entry for entry in data.get("items", []) if entry.get("source_message_id") != message_id
    ]
    if KEY in (state.entity_states or {}):
        state.entity_states = {**state.entity_states, KEY: data}


def remap(states: dict, ids: dict[str, str]) -> dict:
    if KEY not in states:
        return states
    data = deepcopy(states[KEY])
    data["items"] = [
        entry for entry in data.get("items", []) if entry.get("source_message_id") in ids
    ]
    for entry in data["items"]:
        entry["source_message_id"] = ids[entry["source_message_id"]]
        entry["placed_by_message_id"] = entry["source_message_id"]
    return {**states, KEY: data}


def invalidate(state: Any) -> None:
    data = deepcopy((state.entity_states or {}).get(KEY) or {})
    for entry in data.get("items", []):
        entry["status"] = "provisional"
    if KEY in (state.entity_states or {}):
        state.entity_states = {**state.entity_states, KEY: data}
