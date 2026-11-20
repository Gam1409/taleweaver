"""Expose placement requirements in the transport schema as well as host validation."""

from copy import deepcopy

from backend.engine.clothing.body_schema import BODY_SLOT_KEYS


def placement_rules(schema: dict) -> None:
    field = schema["properties"]["uncovered_regions"]
    if field.get("type") == "null":
        return  # Recovery uses its existing outer placement contract.
    # Keep partial removal in the same exclusive placement branches. This avoids
    # a second conditional crossing every branch during native schema projection.
    schema["oneOf"] = [
        {
            "properties": {
                "disposition": {"enum": ["carried", "held"]},
                "partially_removed": {"type": "null"},
                "uncovered_regions": {"type": "null"},
                "attachment_slot": {"type": "null"},
            }
        },
        {
            "properties": {
                "disposition": {"const": "worn"},
                "uncovered_regions": {"uniqueItems": True},
                "attachment_slot": {"type": "null"},
            }
        },
        {
            "required": ["attachment_slot"],
            "properties": {
                "disposition": {"const": "worn"},
                "uncovered_regions": {"type": "null"},
                "attachment_slot": {"enum": list(BODY_SLOT_KEYS)},
                "partially_removed": {"type": "null"},
            },
        },
    ]
    _observation_rule(schema)


def _observation_rule(schema: dict) -> None:
    bases = schema["properties"]["basis"].get("enum", [])
    observations = {"observed_placement", "observed_possession"}
    if not observations.intersection(bases):
        return
    legacy = [value for value in bases if value not in observations]
    observed = deepcopy(schema["oneOf"][-1])
    for alternative in schema["oneOf"]:
        alternative["properties"]["basis"] = {"enum": legacy}
    if "observed_placement" in bases:
        _placement_observation(schema, observed)
    if "observed_possession" in bases:
        schema["oneOf"].append(
            {
                "properties": {
                    "basis": {"const": "observed_possession"},
                    "partially_removed": {"type": "null"},
                    "disposition": {"enum": ["carried", "held"]},
                    "source_owner": {"not": {"const": "__scene__"}},
                    "destination_owner": {"not": {"const": "__scene__"}},
                    "uncovered_regions": {"type": "null"},
                    "attachment_slot": {"type": "null"},
                }
            }
        )


def _placement_observation(schema: dict, observed: dict) -> None:
    observed["required"].append("item_id")
    observed["properties"].update(
        basis={"const": "observed_placement"},
        item_id={"type": "string", "minLength": 1},
        new_item={"type": "null"},
    )
    schema["oneOf"].append(observed)
