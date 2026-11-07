"""Compact, creation-only blueprint data; never added to every RP turn."""

import json
from typing import Any

from backend.engine.blueprint.models import Blueprint, BlueprintBlock

COLLECTIONS = {
    "scene": "scenes",
    "exit": "exits",
    "npc": "npcs",
    "item": "objects",
    "sequence": "sequences",
    "script": "scripts",
    "sidequest": "quests",
    "award": "awards",
}


def block_payload(block: BlueprintBlock) -> dict[str, Any]:
    return {
        "kind": block.kind,
        "id": block.ref,
        "fixed": block.fixed(),
        "hints": block.hints(),
        "open": block.open_fields,
        "notes": block.description,
        "children": [block_payload(child) for child in block.children],
    }


def render_blueprint_prompt(blueprint: Blueprint, missing: list[str], strictness: str) -> str:
    payload = [block_payload(block) for block in blueprint.blocks]
    return (
        "\n\nAUTHOR BLUEPRINT (world creation only):\n"
        "Create every declared entity using its exact ID. Sequence N uses ID SEQ_N and order N. Fixed fields are author-owned and "
        "will be reapplied after generation. Hints are suggestions; fill open and omitted fields. "
        "Keep character age, traits, ownership, clothing and all references coherent. "
        "Scripts are sandboxed code; never rewrite fixed code. "
        + (
            "Add only what is needed for a complete playable world. "
            if strictness == "strict"
            else "Creative additions may develop the outline. "
        )
        + f"Referenced IDs to create if missing: {', '.join(missing) or 'none'}.\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )
