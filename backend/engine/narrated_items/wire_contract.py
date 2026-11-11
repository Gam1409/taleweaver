"""Expose placement requirements in the transport schema as well as host validation."""


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
                "attachment_slot": {"enum": ["vaginal", "anal"]},
            },
        },
    ]
