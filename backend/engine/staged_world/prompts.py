"""Canonical context shared by all generation stages, without transcript growth."""

import json
from typing import Any

PLAN_INSTRUCTION = """
STAGED GENERATION: This request is ONLY the compact world plan, not the full world.
Follow the supplied WorldPlan schema instead of the full-world output format.
Keep all story, language, count, mode and user constraints above.
foundation contains the shared plot, setting rules, language and opening. Be concise.
Declare EVERY entity and dependency needed later in the seed registries. Preserve
user-specified technical IDs; use unique ASCII IDs otherwise. protagonist.id is
PROTAGONIST. The FIRST scene is the player's starting scene. Provide connected exits.
Use summary for immutable facts, relationships, motivations, private knowledge,
puzzle solutions and cross-chapter dependencies. It is internal author context:
secrets are NOT automatically known to the player. Use one or two short sentences
per summary; avoid repeating the premise. This is an outline, not finished prose.
For objects, owner_id identifies the single starting owner: PROTAGONIST, an NPC or
container ID; empty means loose in start_scene_id. Set item_type for every object
seed (especially CONTAINER and READABLE), empty for other categories. Every item must be declared,
including equipped items and container contents. NPCs/objects need start_scene_id.
Use name for the eventual title of sequences/quests/awards, id for an award's key.
Record chapter order in the sequences array. Do not invent extra entities during
later detailing. Do not output long biographies, full entity stats or artwork prompts.
For VN, sequences, quests, awards and scripts MUST be empty; do not add RPG goals.
Omit unused optional fields. Output only the requested JSON object.
"""

DETAIL_INSTRUCTION = """
STAGED GENERATION: Expand ONLY the requested entries using the supplied stage schema.
The accepted plan is immutable author context. Preserve IDs, names/titles, initial
placements, ownership, shared facts and language. Do not create new entities or
rewrite the plot. You may add compatible detail, not contradict established facts.
Distinguish private knowledge from player-visible text. Keep technical keys/enums
unchanged and localize all human-readable content. Treat accepted details as canon.
Invent no item IDs: inventories and equipment may reference only planned items
owned by that character/container. Equipped items are also owned, not duplicates.
For switch outcomes, use container IDs or story_flag effects; the exit schema has
no stable exit ID for an unlock_exit effect. Do not invent one.
Return every requested entry exactly once, no other entries. Use the requested order
for sequences. Omit unused optional fields rather than filling pages of empty values.
Keep descriptions focused; avoid repetition and padding. Output only stage JSON.
"""


def detail_context(
    plan: dict[str, Any], kind: str, seeds: list[dict], completed: dict[str, Any]
) -> str:
    """Retain the entire compact plan and exact already generated dependencies.

    Relevant detail is selected by scene/ownership/reference IDs. The full plan
    remains present, so an unrelated scene's existence and secrets are never lost.
    """
    targets = {seed["id"] for seed in seeds}
    locations = {seed.get("start_scene_id") for seed in seeds} - {"", None}
    if kind == "scenes":
        locations.update(targets)
    relevant: dict[str, Any] = {}
    cast_facts: list[dict[str, Any]] = []
    for key, value in completed.items():
        if key == "protagonist":
            relevant[key] = value
        elif key != "plan":
            rows = value.get("items", [])
            if key.startswith("npcs:"):
                cast_facts.extend(_cast_facts(row) for row in rows)
            selected = [row for row in rows if _relevant(row, targets, locations, kind)]
            if selected:
                relevant[key] = selected
    return json.dumps(
        {
            "accepted_plan": plan,
            "stage": kind,
            "requested_entries": seeds,
            "accepted_cast_facts": cast_facts,
            "accepted_details": relevant,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _cast_facts(row: dict) -> dict:
    # Copy exact author facts so cross-scene relationships survive each batch.
    fields = ("id", "name", "description", "goal", "character", "notes", "reveal_rule", "inventory")
    return {key: row[key] for key in fields if key in row}


def _relevant(row: dict, targets: set, locations: set, kind: str) -> bool:
    # Progression/scripts must see implemented mechanics, not just summaries.
    if kind in {"sequences", "quests", "awards", "scripts"}:
        return True
    return (
        row.get("id") in targets | locations
        or row.get("start_scene_id") in locations
        or bool(set(row.get("inventory") or []) & targets)
    )
