"""Expose placement requirements in the transport schema as well as host validation."""

from copy import deepcopy

from backend.engine.clothing.body_schema import BODY_SLOT_KEYS


def placement_rules(schema: dict) -> None:
    field = schema["properties"]["uncovered_regions"]
    if field.get("type") == "null":
        return  # Recovery uses its existing outer placement contract.
    schema["oneOf"] = [
        {
            "properties": {
                "uncovered_regions": {"type": "null"},
                "attachment_slot": {"type": "null"},
            }
        },
        {
            "required": ["uncovered_regions"],
            "properties": {
                "disposition": {"const": "worn"},
                "uncovered_regions": {"type": "array", "uniqueItems": True},
                "attachment_slot": {"type": "null"},
            },
        },
        {
            "required": ["attachment_slot"],
            "properties": {
                "disposition": {"const": "worn"},
                "uncovered_regions": {"type": "null"},
                "attachment_slot": {"enum": list(BODY_SLOT_KEYS)},
            },
        },
    ]
    _observation_rule(schema)


def _observation_rule(schema: dict) -> None:
    bases = schema["properties"]["basis"].get("enum", [])
    if "observed_placement" not in bases:
        return
    legacy = [value for value in bases if value != "observed_placement"]
    observed = deepcopy(schema["oneOf"][-1])
    for alternative in schema["oneOf"]:
        alternative["properties"]["basis"] = {"enum": legacy}
    observed["required"].append("item_id")
    observed["properties"].update(
        basis={"const": "observed_placement"},
        item_id={"type": "string", "minLength": 1},
        new_item={"type": "null"},
    )
    schema["oneOf"].append(observed)
