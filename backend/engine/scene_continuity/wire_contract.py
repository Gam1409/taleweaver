"""Expose the scene operation validator's conditional rules to extracting models."""


def operation_rules(schema: dict) -> None:
    schema["properties"]["evidence"]["pattern"] = r"\S[\s\S]{2,}\S"
    record = {
        "properties": {
            "operation": {"const": "record"},
            "record_id": _blank(),
            "key": _present(),
            "subject_id": _present(),
            "detail": _present(),
        },
        "required": ["key", "subject_id", "detail"],
    }
    change = _existing("change")
    change["properties"]["detail"] = _present()
    change["required"].append("detail")
    schema["oneOf"] = [record, change, _existing("end")]
    schema["allOf"] = [
        {
            "if": {
                "properties": {"source": {"const": "scene_description"}},
                "required": ["source"],
            },
            "then": {"properties": {"kind": {"const": "environment"}}, "required": ["kind"]},
        }
    ]


def _existing(operation: str) -> dict:
    return {
        "properties": {
            "operation": {"const": operation},
            "record_id": _present(),
            "key": _blank(),
            "subject_id": _blank(),
        },
        "required": ["record_id"],
    }


def _blank() -> dict:
    return {"type": "string", "pattern": r"^\s*$"}


def _present() -> dict:
    return {"type": "string", "minLength": 1, "pattern": r"\S"}
