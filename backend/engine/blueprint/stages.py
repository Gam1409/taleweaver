"""Bind author constraints before staged plan/detail validation and checkpointing."""

from copy import deepcopy
from typing import cast

from backend.engine.blueprint.merge import BlueprintMergeError
from backend.engine.blueprint.models import Blueprint, BlueprintBlock
from backend.engine.blueprint.prompt import COLLECTIONS


def _identifier(block: BlueprintBlock) -> str:
    return f"SEQ_{block.ref}" if block.kind == "sequence" else block.ref


def _seed(plan: dict, block: BlueprintBlock) -> dict:
    if block.kind == "protagonist":
        return cast(dict, plan["protagonist"])
    if block.kind == "world":
        return cast(dict, plan["foundation"])
    if block.kind == "exit":
        pair = (block.fixed().get("from_scene_id"), block.fixed().get("to_scene_id"))
        seed = next(
            (e for e in plan["exits"] if (e["from_scene_id"], e["to_scene_id"]) == pair), None
        )
    else:
        seed = next(
            (e for e in plan[COLLECTIONS[block.kind]] if e["id"] == _identifier(block)), None
        )
    if seed is None:
        raise BlueprintMergeError(
            f"Plan omitted declared {block.kind} '{_identifier(block)}' (line {block.line})."
        )
    return cast(dict, seed)


def _owned_items(block: BlueprintBlock) -> set[str]:
    fixed = block.fixed()
    inventory = fixed.get("starting_inventory" if block.kind == "protagonist" else "inventory", [])
    equipment = (fixed.get("starting_equipment") or {}).values()
    worn = (fixed.get("visual_profile") or {}).get("worn", [])
    return set(inventory) | {ref for ref in equipment if ref} | {entry["item_id"] for entry in worn}


def bind_plan(plan: dict, blueprint: Blueprint) -> None:
    """Fix identity/location and ownership before the existing plan validators run."""
    owners: dict[str, str] = {}
    for block in blueprint.blocks:
        seed = _seed(plan, block)
        fixed = block.fixed()
        fields = (
            fixed
            if block.kind in {"world", "exit"}
            else {
                key: value
                for key, value in fixed.items()
                if key in {"name", "start_scene_id", "item_type"}
            }
        )
        if block.kind in {"sequence", "sidequest", "award"} and "title" in fixed:
            fields["name"] = fixed["title"]
        seed.update(deepcopy(fields))
        owner = "PROTAGONIST" if block.kind == "protagonist" else block.ref
        for item in _owned_items(block):
            if item in owners and owners[item] != owner:
                raise BlueprintMergeError(f"Blueprint gives '{item}' to multiple owners.")
            owners[item] = owner
    for item in plan["objects"]:
        if item["id"] in owners:
            item["owner_id"] = owners[item["id"]]


def bind_detail(kind: str, rows: list[dict], blueprint: Blueprint) -> None:
    """Only authored fields are reapplied; existing ownership binding still validates the batch."""
    blocks = [
        b
        for b in blueprint.blocks
        if COLLECTIONS.get(b.kind) == kind or b.kind == kind == "protagonist"
    ]
    for row in rows:
        for block in blocks:
            id_field = "key" if kind == "awards" else "id"
            if kind != "protagonist" and row.get(id_field) != _identifier(block):
                continue
            row.update(deepcopy(block.fixed()))
            if block.kind == "sequence":
                row["id"] = _identifier(block)
                row["order"] = int(block.ref)
