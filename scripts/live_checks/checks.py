"""Canonical observations are distinct from narrative/psychological judgments."""

import json

from backend.engine.physical_conditions.ledger import read


def ownership(snapshot: dict, item_id: str) -> list[str]:
    states = snapshot["state"]["entity_states"] or {}
    found = (
        ["__player__"]
        if any(item.get("id") == item_id for item in snapshot["avatar"]["inventory"])
        else []
    )
    for entity in snapshot["tables"]["world_entities"]:
        override = states.get(entity["id"], {})
        inventory = override.get("inventory", entity.get("inventory")) or []
        if any(isinstance(item, dict) and item.get("id") == item_id for item in inventory):
            found.append(entity["id"])
        if entity["id"] == item_id and not override.get(
            "is_in_inventory", entity["is_in_inventory"]
        ):
            found.append("__scene__")
    return found


def state_expectations(scenario: str, snapshot: dict) -> list[str]:
    errors = []
    if scenario.startswith("place_") and ownership(snapshot, "SILVER_FLASK") != ["__scene__"]:
        errors.append("The known flask did not move to the scene under its original identity.")
    if scenario.startswith("wear_"):
        worn = (snapshot["avatar"].get("visual_profile") or {}).get("worn", [])
        rows = [row for row in worn if row["item_id"] == "GREEN_COAT"]
        if (
            ownership(snapshot, "GREEN_COAT") != ["__player__"]
            or not rows
            or "arms" not in rows[0].get("uncovered_regions", [])
        ):
            errors.append(
                "Raised sleeves were not reflected as a still-owned, still-worn displaced garment."
            )
    if scenario == "player_movement" and snapshot["state"]["current_scene_id"] != "PORCH":
        errors.append("The explicit open-route travel was not committed to PORCH.")
    if scenario == "condition_history":
        current = read(snapshot["state"]["entity_states"]).conditions.values()
        active = {
            row.kind
            for row in current
            if row.target_id == "__player__" and row.status != "resolved"
        }
        if "injury" not in active or "contamination" in active:
            errors.append("Cleaning must resolve dirt while retaining the independent injury.")
    return errors


def technical_checks(
    case, before: dict, after: dict, calls: list[dict], tools: list[dict], public: str, secret: str
) -> list[str]:
    errors = state_expectations(case.scenario, after) if case.group == "state" else []
    if any(
        len(ownership(after, item)) > 1
        for item in ("GREEN_COAT", "BLUE_COAT", "SILVER_FLASK", "LANTERN", "SPARE_COAT")
    ):
        errors.append("One canonical item appears to have multiple current owners.")
    if before["notebooks"].get("ABSENT") != after["notebooks"].get("ABSENT"):
        errors.append("Another NPC's notebook changed.")
    if (
        secret in public
        or secret in json.dumps([row["request"] for row in calls])
        or secret in json.dumps(tools)
    ):
        errors.append("Another NPC's private notebook leaked to a model/public/tool projection.")
    return errors


def tool_coverage(tools: list[dict]) -> dict:
    names = [row["request"]["tool"] for row in tools]
    return {
        "executed": names,
        "notebook_write_exercised": any(
            name in {"notebook_write", "notebook_edit"} for name in names
        ),
        "notebook_read_exercised": "notebook_read" in names,
        "feedback_statuses": [row["result"].get("status") for row in tools],
        "interpretation": "A missing operation is not exercised; a narrated claim does not establish tool use.",
    }
