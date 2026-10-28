"""Hydrate VN possession proposals from current canonical items, never model attributes."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from pydantic import ConfigDict

from backend.engine.llm_intents import ChatProgressionIntent
from backend.engine.npc_presence import physically_present
from backend.engine.rule_engine import InventoryItem, WorldEntityUpdate

PLAYER = "__player__"
SCENE = "__scene__"


class CanonicalInventoryItem(InventoryItem):
    """Preserve existing inventory metadata; this type is never sent to the LLM."""

    model_config = ConfigDict(extra="allow")


@dataclass
class Possessions:
    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    owners: dict[str, str] = field(default_factory=dict)
    npcs: dict[str, dict[str, Any]] = field(default_factory=dict)
    containers: dict[str, dict[str, Any]] = field(default_factory=dict)
    catalog: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(self, raw: Any, owner: str) -> None:
        for entry in raw if isinstance(raw, list) else []:
            item = self.catalog.get(entry) if isinstance(entry, str) else entry
            if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
                continue
            item_id = str(item["id"])
            if item_id in self.items:
                continue
            self.items[item_id] = deepcopy(item)
            self.owners[item_id] = owner


def _override(state: Any, entity_id: str) -> dict:
    raw = (state.entity_states or {}).get(entity_id, {})
    return raw if isinstance(raw, dict) else {}


def _present(manager: Any, entity: Any) -> bool:
    state = manager.state
    override = _override(state, entity.id)
    session_id = getattr(entity, "session_id", None)
    return (
        physically_present(entity, state)
        and (not session_id or session_id == getattr(state, "session_id", None))
        and override.get("current_scene_id", entity.current_scene_id) == state.current_scene_id
        and not override.get("is_hidden", getattr(entity, "is_hidden", False))
    )


def _inventory(entity: Any, override: dict) -> list:
    if "inventory" in override:
        return override["inventory"] if isinstance(override["inventory"], list) else []
    direct = getattr(entity, "inventory", None)
    meta = getattr(entity, "metadata_json", None) or {}
    raw = direct or meta.get("inventory") or []
    return raw if isinstance(raw, list) else []


def _entity_item(entity: Any, override: dict) -> dict:
    meta = getattr(entity, "metadata_json", None) or {}
    result = deepcopy(meta)
    carried = override.get("vn_item_data")
    if isinstance(carried, dict):
        result.update(deepcopy(carried))
    for key in InventoryItem.model_fields:
        value = override.get(key, getattr(entity, key, None))
        if value is not None:
            result[key] = value
    result.update(id=entity.id, name=override.get("name", entity.name))
    return result


def _open_container(entity: Any, override: dict) -> bool:
    if str(getattr(entity, "item_type", "")).upper() != "CONTAINER":
        return False
    if isinstance(override.get("locked"), bool):
        return not override["locked"]
    meta = getattr(entity, "metadata_json", None) or {}
    return not meta.get("locked") and not any(
        meta.get(key) for key in ("code_to_unlock", "item_to_unlock", "rule_to_unlock")
    )


def possession_snapshot(manager: Any, entities: list[Any]) -> Possessions:
    """Current location only; retained player items take precedence over shadow world rows."""
    result = Possessions(
        catalog={
            entity.id: _entity_item(entity, _override(manager.state, entity.id))
            for entity in entities
            if entity.entity_type == "OBJECT"
        }
    )
    result.add(getattr(manager.avatar, "inventory", None), PLAYER)
    equipment = getattr(manager.avatar, "equipment", None) or {}
    result.add(
        [value for value in equipment.values() if isinstance(value, dict)]
        if isinstance(equipment, dict)
        else [],
        PLAYER,
    )
    present = [entity for entity in entities if _present(manager, entity)]
    for entity in present:
        if str(entity.entity_type).upper() != "NPC":
            continue
        override = _override(manager.state, entity.id)
        inventory = _inventory(entity, override)
        result.add(inventory, entity.id)
        result.npcs[entity.id] = {
            "id": entity.id,
            "name": override.get("name", entity.name),
            "scene_id": manager.state.current_scene_id,
            "position": override.get("spatial_position", getattr(entity, "spatial_position", None)),
            "inventory": [
                item
                for item_id, item in result.items.items()
                if result.owners[item_id] == entity.id
            ],
        }
    contained = {
        str(item.get("id") if isinstance(item, dict) else item)
        for entity in present
        for item in _inventory(entity, _override(manager.state, entity.id))
    }
    for entity in present:
        override = _override(manager.state, entity.id)
        if str(entity.entity_type).upper() != "OBJECT" or entity.id in contained:
            continue
        if _open_container(entity, override):
            inventory = _inventory(entity, override)
            result.containers[entity.id] = {
                "id": entity.id,
                "name": entity.name,
                "inventory": inventory,
            }
            result.add(inventory, entity.id)
        if override.get("is_in_inventory", getattr(entity, "is_in_inventory", False)):
            continue
        if not getattr(entity, "is_portable", True):
            continue
        result.add([_entity_item(entity, override)], SCENE)
    return result


def _canonical(snapshot: Possessions, item_id: str) -> CanonicalInventoryItem:
    return CanonicalInventoryItem.model_validate(deepcopy(snapshot.items[item_id]))


def _assign(destinations: dict[str, str], snapshot: Possessions, item_id: str, owner: str) -> None:
    if item_id not in snapshot.items:
        raise ValueError("Unknown or unavailable item.")
    if item_id in destinations and destinations[item_id] != owner:
        raise ValueError("Conflicting item destinations.")
    destinations[item_id] = owner


def _destinations(intent: ChatProgressionIntent, snapshot: Possessions) -> dict[str, str]:
    result: dict[str, str] = {}
    for owner, items in ((PLAYER, intent.new_inventory_items), (SCENE, intent.spawned_items)):
        for item in items or []:
            _assign(result, snapshot, item.id, owner)
    for update in intent.updated_entities or []:
        if update.inventory is None:
            continue
        if update.entity_id not in snapshot.npcs and update.entity_id not in snapshot.containers:
            raise ValueError("Inventory owner is not present or accessible.")
        for item in update.inventory:
            if snapshot.owners.get(item.id) != update.entity_id:
                _assign(result, snapshot, item.id, update.entity_id)
            elif item.id not in snapshot.items:
                raise ValueError("Unknown inventory item.")
    return result


def _validate_player_changes(
    intent: ChatProgressionIntent, snapshot: Possessions, destinations: dict[str, str]
) -> None:
    ids = [
        *(intent.removed_inventory_item_ids or []),
        *[i.id for i in intent.updated_inventory_items or []],
    ]
    if any(snapshot.owners.get(item_id) != PLAYER for item_id in ids):
        raise ValueError("The player does not carry this item.")
    if any(item_id not in snapshot.items for item_id in intent.deleted_entities or []):
        raise ValueError("Only existing available items can be consumed or removed.")
    removed = set(intent.removed_inventory_item_ids or [])
    if removed - destinations.keys() - set(intent.deleted_entities or []):
        raise ValueError("Removal needs a confirmed destination or consumption event.")


def _holder_updates(
    intent: ChatProgressionIntent,
    snapshot: Possessions,
    destinations: dict[str, str],
    removed: set[str],
) -> list[WorldEntityUpdate]:
    updates = {update.entity_id: update for update in intent.updated_entities or []}
    affected = {
        owner
        for item_id, owner in snapshot.owners.items()
        if item_id in destinations or item_id in removed
    } | set(destinations.values())
    requested = {update.entity_id for update in updates.values() if update.inventory is not None}
    for npc_id in (affected | requested) & (snapshot.npcs.keys() | snapshot.containers.keys()):
        kept = [
            item_id
            for item_id, owner in snapshot.owners.items()
            if destinations.get(item_id, owner) == npc_id and item_id not in removed
        ]
        update = updates.setdefault(npc_id, WorldEntityUpdate(entity_id=npc_id))
        update.inventory = [_canonical(snapshot, item_id) for item_id in kept]
    return list(updates.values())


def _hydrate(intent: ChatProgressionIntent, snapshot: Possessions) -> None:
    destinations = _destinations(intent, snapshot)
    _validate_player_changes(intent, snapshot, destinations)
    removed = set(intent.deleted_entities or [])
    if removed & destinations.keys():
        raise ValueError("An item cannot be consumed and transferred in the same proposal.")
    intent.new_inventory_items = [
        _canonical(snapshot, item_id)
        for item_id, owner in destinations.items()
        if owner == PLAYER and snapshot.owners[item_id] != PLAYER
    ]
    intent.spawned_items = [
        _canonical(snapshot, item_id)
        for item_id, owner in destinations.items()
        if owner == SCENE and snapshot.owners[item_id] != SCENE
    ]
    player_removed = {
        item_id
        for item_id, owner in snapshot.owners.items()
        if owner == PLAYER and (destinations.get(item_id, PLAYER) != PLAYER or item_id in removed)
    }
    player_removed.update(intent.removed_inventory_item_ids or [])
    if any(destinations.get(item_id) == PLAYER for item_id in player_removed):
        raise ValueError("A player item cannot be removed and retained in the same proposal.")
    intent.removed_inventory_item_ids = sorted(player_removed)
    hydrated_updates = []
    for item in intent.updated_inventory_items or []:
        known = _canonical(snapshot, item.id)
        # Identity is immutable here; condition annotations are applied separately.
        for key in ("spatial_position",):
            value = getattr(item, key)
            if value is not None:
                setattr(known, key, value)
        hydrated_updates.append(known)
    intent.updated_inventory_items = hydrated_updates
    intent.updated_entities = _holder_updates(intent, snapshot, destinations, removed)


def prepare_intent(manager: Any, intent: Any, entities: list[Any]) -> ChatProgressionIntent:
    """Return an engine-ready intent; reject an invalid possession batch without losing items."""
    from backend.engine.visual_novel.intent import VNProgressionIntent, to_chat_progression_intent

    raw = intent.model_dump(exclude_none=True) if hasattr(intent, "model_dump") else intent
    proposal = VNProgressionIntent.model_validate(raw)
    result = to_chat_progression_intent(proposal)
    try:
        _hydrate(result, possession_snapshot(manager, entities))
        conditions = {
            item.id: item.condition_note
            for item in proposal.updated_inventory_items or []
            if item.condition_note is not None
        }
        for item in result.updated_inventory_items or []:
            if item.id in conditions:
                item.condition_note = conditions[item.id]
        if any(
            proposed.name != item.name
            or (proposed.description is not None and proposed.description != item.description)
            for proposed, item in zip(
                proposal.updated_inventory_items or [],
                result.updated_inventory_items or [],
                strict=False,
            )
        ):
            result.narrative_description += " Existing item identity, type and base description remain unchanged; only explicit condition notes may change."
    except (ValueError, TypeError):
        result.new_inventory_items = []
        result.updated_inventory_items = []
        result.removed_inventory_item_ids = []
        result.spawned_items = []
        result.deleted_entities = []
        for update in result.updated_entities or []:
            update.inventory = None
        result.narrative_description = (
            "The attempted item change did not occur; possessions remain unchanged."
        )
    return result
