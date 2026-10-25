"""Pure integrity checks for frozen world plans and incremental model responses."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from backend.core.world_validation.topology import build_adjacency, reachable_scenes
from backend.engine.world_schemas import WorldExitSchema

CATEGORIES = ("scenes", "npcs", "objects", "sequences", "quests", "awards", "scripts")
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_ITEM_FIELDS = {
    "item_to_unlock",
    "reveals_item_id",
    "required_item_id",
    "equipped_weapon_id",
    "equipped_armor_id",
    "unlock_condition_target",
    "unlock_required_item_id",
}
_SCENE_FIELDS = {
    "start_scene_id",
    "from_scene_id",
    "to_scene_id",
    "required_scene_id",
    "unlock_required_scene_id",
}
_NPC_FIELDS = {"required_defeated_npc_id", "unlock_required_defeated_npc_id"}


def _index(plan: dict[str, Any], kind: str) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in plan.get(kind, [])}


def _require_ref(value: Any, valid: set[str], path: str) -> None:
    if value in (None, ""):
        return
    if not isinstance(value, str) or value not in valid:
        raise ValueError(f"{path} references unknown ID {value!r}.")


def _validate_ids(plan: dict[str, Any]) -> None:
    seen = {"PROTAGONIST"}
    for kind in CATEGORIES:
        for row in plan.get(kind, []):
            identifier = row.get("id")
            _validate_seed(row, identifier, seen, kind)
            seen.add(identifier)


def _validate_seed(row: dict[str, Any], identifier: Any, seen: set[str], kind: str) -> None:
    if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
        raise ValueError(f"{kind}: IDs must use ASCII letters, digits and underscores (max 64).")
    if identifier in seen:
        raise ValueError(f"Duplicate planned ID {identifier!r}; every world ID must be unique.")
    if not isinstance(row.get("name"), str) or not row["name"].strip():
        raise ValueError(f"{kind}.{identifier} needs a name.")


def _validate_ownership_plan(plan: dict[str, Any]) -> None:
    objects = _index(plan, "objects")
    owners = set(objects) | set(_index(plan, "npcs")) | {"PROTAGONIST"}
    for identifier, row in objects.items():
        _require_ref(row.get("owner_id"), owners, f"objects.{identifier}.owner_id")
        chain = {identifier}
        owner = row.get("owner_id")
        while owner in objects:
            if owner in chain:
                raise ValueError(f"Cyclic item ownership involving {identifier!r}.")
            chain.add(owner)
            owner = objects[owner].get("owner_id")


def _validate_topology(plan: dict[str, Any]) -> None:
    scenes = plan.get("scenes") or []
    if not scenes:
        raise ValueError("The world plan needs at least one scene.")
    scene_ids = set(_index(plan, "scenes"))
    for exit_ in plan.get("exits", []):
        _require_ref(exit_.get("from_scene_id"), scene_ids, "exit.from_scene_id")
        _require_ref(exit_.get("to_scene_id"), scene_ids, "exit.to_scene_id")
    reachable = reachable_scenes(scenes[0]["id"], build_adjacency(plan.get("exits", [])))
    missing = sorted(scene_ids - reachable)
    if missing:
        raise ValueError(f"Scenes unreachable from the first scene: {', '.join(missing)}.")


def _validate_owner_locations(plan: dict[str, Any]) -> None:
    locations = {
        row["id"]: row["start_scene_id"]
        for kind in ("npcs", "objects")
        for row in plan.get(kind, [])
    }
    locations["PROTAGONIST"] = plan["scenes"][0]["id"]
    for row in plan.get("objects", []):
        owner = row.get("owner_id")
        if owner and row["start_scene_id"] != locations[owner]:
            raise ValueError(
                f"Object {row['id']!r} must start in its owner's planned scene {locations[owner]!r}."
            )


def validate_plan(plan: dict[str, Any]) -> None:
    """Reject ambiguous identities, dangling references and impossible ownership."""
    protagonist = plan.get("protagonist") or {}
    if protagonist.get("id") != "PROTAGONIST" or not protagonist.get("name"):
        raise ValueError("The plan needs a named protagonist with ID PROTAGONIST.")
    _validate_ids(plan)
    _validate_ownership_plan(plan)
    _validate_topology(plan)
    scenes = set(_index(plan, "scenes"))
    for kind in ("npcs", "objects"):
        for row in plan.get(kind, []):
            if not row.get("start_scene_id"):
                raise ValueError(f"{kind}.{row['id']} needs a planned start_scene_id.")
            _require_ref(row["start_scene_id"], scenes, f"{kind}.{row['id']}.start_scene_id")
    _validate_owner_locations(plan)
    _validate_references(plan.get("exits", []), plan, "exits")


def _walk(value: Any, path: str) -> Iterator[tuple[str, Any, str]]:
    if isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child, f"{path}.{key}"
            yield from _walk(child, f"{path}.{key}")


def _reference_sets(plan: dict[str, Any]) -> dict[str, set[str]]:
    objects, scenes, npcs = (set(_index(plan, kind)) for kind in ("objects", "scenes", "npcs"))
    return {
        **dict.fromkeys(_ITEM_FIELDS, objects),
        **dict.fromkeys(_SCENE_FIELDS, scenes),
        **dict.fromkeys(_NPC_FIELDS, npcs),
        "item": objects,
    }


def _validate_references(value: Any, plan: dict[str, Any], path: str) -> None:
    references = _reference_sets(plan)
    objects = set(_index(plan, "objects"))
    list_fields = {
        "inventory": objects,
        "starting_inventory": objects,
        "combination_ingredients": objects,
        "allowed_scenes": set(_index(plan, "scenes")),
    }
    for key, child, location in _walk(value, path):
        if key in references:
            _require_ref(child, references[key], location)
        if key in list_fields:
            for ref in child or []:
                _require_ref(ref, list_fields[key], location)
        if key == "starting_equipment" and isinstance(child, dict):
            for slot, ref in child.items():
                _require_ref(ref, objects, f"{location}.{slot}")
    _validate_targets(value, plan, path)


def _validate_targets(value: Any, plan: dict[str, Any], path: str) -> None:
    entities = set(_index(plan, "objects")) | set(_index(plan, "npcs"))
    scenes = set(_index(plan, "scenes"))
    exits = {exit_["id"] for exit_ in plan.get("exits", []) if exit_.get("id")}
    for key, child, location in _walk(value, path):
        if key == "switch_outcomes":
            _validate_switch_targets(child or [], plan, exits, location)
        if key == "target_id" and ".switch_outcomes" not in location:
            _require_ref(child, scenes | entities, location)


def _validate_switch_targets(
    outcomes: list[dict[str, Any]], plan: dict[str, Any], exits: set[str], path: str
) -> None:
    for outcome in outcomes:
        for effect in outcome.get("effects", []):
            kind = effect.get("type")
            allowed = exits if kind == "unlock_exit" else set(_index(plan, "objects"))
            if kind in {"unlock_exit", "unlock_container"}:
                _require_ref(effect.get("target_id"), allowed, f"{path}.{kind}.target_id")


def _identity(kind: str, row: dict[str, Any]) -> tuple[str, Any]:
    identifier = row.get("key") if kind == "awards" else row.get("id")
    name_field = "title" if kind in {"sequences", "quests", "awards"} else "name"
    return identifier, row.get(name_field)


def _validate_row(kind: str, row: dict[str, Any], plan: dict[str, Any]) -> str:
    identifier, name = _identity(kind, row)
    seeds = _index(plan, kind)
    if identifier not in seeds:
        raise ValueError(f"{kind}: unplanned ID {identifier!r}.")
    seed = seeds[identifier]
    if name != seed["name"]:
        raise ValueError(f"{kind}.{identifier}: keep the planned name {seed['name']!r}.")
    if kind in {"npcs", "objects"} and row.get("start_scene_id") != seed.get("start_scene_id"):
        raise ValueError(f"{kind}.{identifier}: keep the planned start_scene_id.")
    if kind == "sequences" and row.get("order") != list(seeds).index(identifier) + 1:
        raise ValueError(f"sequences.{identifier}: keep the planned sequence order.")
    if kind == "objects":
        _validate_item_type(row, seed)
    _validate_references(row, plan, f"{kind}.{identifier}")
    if kind in {"npcs", "objects"}:
        _validate_holder(identifier, row, plan, container=kind == "objects")
    return identifier


def _validate_item_type(row: dict[str, Any], seed: dict[str, Any]) -> None:
    if seed.get("item_type") and row.get("item_type") != seed["item_type"]:
        raise ValueError(f"objects.{seed['id']}: keep the planned item_type {seed['item_type']!r}.")


def validate_batch(kind: str, rows: Any, plan: dict[str, Any]) -> None:
    """Validate a subset; the orchestrator additionally checks its requested batch IDs."""
    if kind == "protagonist":
        row = rows[0] if isinstance(rows, list) and len(rows) == 1 else rows
        if not isinstance(row, dict) or row.get("name") != plan["protagonist"]["name"]:
            raise ValueError("Protagonist response must keep the planned name.")
        _validate_references(row, plan, "protagonist")
        _validate_holder("PROTAGONIST", row, plan)
        return
    if kind not in CATEGORIES or not isinstance(rows, list):
        raise ValueError(f"Unknown world batch category {kind!r} or invalid batch response.")
    identifiers = [_validate_row(kind, row, plan) for row in rows]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{kind}: batch contains duplicate IDs.")


def _owner_items(row: dict[str, Any], *, protagonist: bool = False) -> set[str]:
    if protagonist:
        equipment = (row.get("starting_equipment") or {}).values()
        return set(row.get("starting_inventory") or []) | {ref for ref in equipment if ref}
    inventory = set(row.get("inventory") or [])
    equipment = {row.get("equipped_weapon_id"), row.get("equipped_armor_id")} - {None, ""}
    return inventory | equipment


def _validate_holder(
    identifier: str, row: dict[str, Any], plan: dict[str, Any], *, container: bool = False
) -> None:
    expected = {
        seed["id"] for seed in plan.get("objects", []) if seed.get("owner_id") == identifier
    }
    actual = _owner_items(row, protagonist=identifier == "PROTAGONIST")
    if actual != expected:
        raise ValueError(
            f"{identifier}: inventory and equipment must match planned owner assignments."
        )
    if container and expected and row.get("item_type") != "CONTAINER":
        raise ValueError(f"Object {identifier!r} owns items and must be a CONTAINER.")


def _validate_manifest_ownership(manifest: dict[str, Any], plan: dict[str, Any]) -> None:
    actual: dict[str, set[str]] = {}
    holders = [("PROTAGONIST", _owner_items(manifest["protagonist"], protagonist=True))]
    holders += [(row["id"], _owner_items(row)) for row in manifest.get("npcs", [])]
    holders += [(row["id"], _owner_items(row)) for row in manifest.get("objects", [])]
    for owner, items in holders:
        for identifier in items:
            actual.setdefault(identifier, set()).add(owner)
    for identifier, seed in _index(plan, "objects").items():
        expected = {seed["owner_id"]} if seed.get("owner_id") else set()
        if actual.get(identifier, set()) != expected:
            raise ValueError(
                f"Object {identifier!r} must have only its planned owner {seed.get('owner_id') or '(scene)'!r}."
            )
    containers = {seed.get("owner_id") for seed in plan.get("objects", [])}
    for row in manifest.get("objects", []):
        if row["id"] in containers and row.get("item_type") != "CONTAINER":
            raise ValueError(f"Object {row['id']!r} owns items and must be a CONTAINER.")


def validate_manifest(manifest: dict[str, Any], plan: dict[str, Any]) -> None:
    """Validate an assembled, schema-checked world before any playable rows are written."""
    validate_plan(plan)
    validate_batch("protagonist", manifest.get("protagonist"), plan)
    for kind in CATEGORIES:
        rows = manifest.get(kind, [])
        validate_batch(kind, rows, plan)
        if {_identity(kind, row)[0] for row in rows} != set(_index(plan, kind)):
            raise ValueError(f"{kind}: assembled world must contain every planned ID exactly once.")
    frozen_exits = [
        WorldExitSchema.model_validate(row).model_dump() for row in plan.get("exits", [])
    ]
    actual_exits = [
        WorldExitSchema.model_validate(row).model_dump() for row in manifest.get("exits", [])
    ]
    if actual_exits != frozen_exits:
        raise ValueError("The assembled world must preserve the planned exits.")
    if [row["id"] for row in manifest["scenes"]] != [row["id"] for row in plan["scenes"]]:
        raise ValueError("Keep planned scene order so the starting scene cannot change.")
    _validate_manifest_ownership(manifest, plan)
