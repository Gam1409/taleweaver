"""Reapply author fields atomically, validate the result and report missing entities."""

from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from backend.engine.blueprint.models import Blueprint, BlueprintBlock
from backend.engine.blueprint.prompt import COLLECTIONS
from backend.engine.world_schemas import WorldManifesto


class BlueprintMergeError(ValueError):
    """Generated content cannot satisfy the author's blueprint without inventing records."""


def _find(manifest: dict, block: BlueprintBlock) -> dict | None:
    if block.kind == "world":
        return manifest
    if block.kind == "protagonist":
        return manifest.get("protagonist")
    for entry in manifest.get(COLLECTIONS[block.kind], []):
        if not isinstance(entry, dict):
            continue
        if block.kind == "exit":
            fixed = block.fixed()
            if (entry.get("from_scene_id"), entry.get("to_scene_id")) == (
                fixed.get("from_scene_id"),
                fixed.get("to_scene_id"),
            ):
                return entry
            continue
        key = {"sequence": "order", "award": "key"}.get(block.kind, "id")
        if str(entry.get(key, "")).upper() == block.ref:
            return entry
    return None


def _apply(entry: dict, block: BlueprintBlock) -> None:
    entry.update(deepcopy(block.fixed()))
    for child in block.children:
        if child.kind != "ability":
            raise BlueprintMergeError(
                f"Unsupported nested block '{child.kind}' on line {child.line}."
            )
        abilities = entry.setdefault("special_actions", [])
        target = next((a for a in abilities if a.get("id") == child.ref), None)
        if target is None:
            target = {
                "id": child.ref,
                "name": child.name or child.ref,
                "description": child.description or child.ref,
                "action_type": "UTILITY",
            }
            abilities.append(target)
        _apply(target, child)


def apply_blueprint(manifest: dict[str, Any], blueprint: Blueprint) -> dict[str, Any]:
    """Return a validated copy; the caller's manifest is unchanged even on failure."""
    candidate = deepcopy(manifest)
    missing = []
    for block in blueprint.blocks:
        entry = _find(candidate, block)
        if entry is None:
            missing.append(f"{block.kind} '{block.ref}' (line {block.line})")
            continue
        _apply(entry, block)
    if missing:
        raise BlueprintMergeError(
            "Generated world omitted declared blueprint entries: " + "; ".join(missing)
        )
    try:
        validated = WorldManifesto.model_validate(candidate).model_dump()
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_url=False)[:8]
        )
        raise BlueprintMergeError("Blueprint fields do not form a valid world: " + details) from exc
    return {**candidate, **validated}
