"""Expose operation-dependent requirements without changing the persisted condition shape."""


def operation_rules(schema: dict) -> None:
    """The proposal model's cross-field rules must also reach the extracting model."""
    schema["properties"]["evidence"]["pattern"] = r"\S[\s\S]{2,}\S"
    record = {
        "properties": {
            "operation": {"const": "record"},
            "condition_id": _blank_nullable(),
            "target_id": {"type": "string", "minLength": 1, "pattern": r"\S"},
            "kind": {"type": "string"},
            "part": {"minLength": 1, "pattern": r"\S"},
            "detail": {"minLength": 1, "pattern": r"\S"},
        },
        "required": ["target_id", "kind", "part", "detail"],
    }
    change = _update(["change"])
    change["properties"]["detail"] = {"minLength": 1, "pattern": r"\S"}
    change["required"].append("detail")
    schema["oneOf"] = [record, change, _update(["treat", "reduce", "clean", "heal", "remove"])]


def _update(operations: list[str]) -> dict:
    return {
        "properties": {
            "operation": {"enum": operations},
            "condition_id": {"type": "string", "minLength": 1, "pattern": r"\S"},
            "target_id": _blank_nullable(),
            "kind": {"type": "null"},
            "part": {"pattern": r"^\s*$"},
        },
        "required": ["condition_id"],
    }


def _blank_nullable() -> dict:
    return {"anyOf": [{"type": "null"}, {"type": "string", "pattern": r"^\s*$"}]}
