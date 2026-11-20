"""Expose existing experience invariants without changing canonical state or wire fields."""

from backend.engine.chpm.core.contracts import AFFECT_DIMENSIONS


def rules(schema: dict) -> None:
    """Disjoint channels keep decoder choices consistent with the state owner's validator."""
    fields = schema["properties"]
    dimensions = fields["dimension"].pop("enum")
    channels = fields["channel"].pop("enum")
    schema["oneOf"] = [
        {
            "properties": {
                "channel": {"const": "affect"},
                "dimension": {
                    "enum": [value for value in dimensions if value in AFFECT_DIMENSIONS]
                },
            }
        },
        {
            "properties": {
                "channel": {"enum": [value for value in channels if value != "affect"]},
                "dimension": {
                    "enum": [value for value in dimensions if value not in AFFECT_DIMENSIONS]
                },
                "about_id": {"type": "null"},
            }
        },
    ]
    fields["about_id"]["description"] = (
        "Affect toward a known_subjects ID or null. For an item or situation use null and "
        "ground the trigger in the explanation/citations. Needs use null (observer implicit)."
    )
