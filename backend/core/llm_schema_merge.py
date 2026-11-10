"""Bounded intersections used to expand operation branches for decoder schemas."""

from copy import deepcopy
from typing import Any, Literal


class SchemaProjectionError(ValueError):
    """The wire representation needs a weaker, explicitly reported output mode."""


def intersect(left: dict | bool, right: dict | bool) -> dict | Literal[False]:
    if left is False or right is False:
        return False
    a = deepcopy(left) if isinstance(left, dict) else {}
    b = deepcopy(right) if isinstance(right, dict) else {}
    for keyword in ("anyOf", "oneOf"):
        if keyword in a:
            branches = a.pop(keyword)
            return {"anyOf": [intersect(intersect(a, branch), b) for branch in branches]}
        if keyword in b:
            return intersect(b, a)
    if "$ref" in a and b or "$ref" in b and a:
        raise SchemaProjectionError("A reference intersection needs local schema validation.")
    if not _compatible_types(a.get("type"), b.get("type")):
        return False
    result = {**a, **b}
    if {a.get("type"), b.get("type")} == {"number", "integer"}:
        result["type"] = "integer"
    _object_fields(result, a, b)
    for key in ("minLength", "minItems", "minProperties", "minimum"):
        _bound(result, a, b, key, max)
    for key in ("maxLength", "maxItems", "maxProperties", "maximum"):
        _bound(result, a, b, key, min)
    return _finite(result, a, b)


def _object_fields(result: dict, left: dict, right: dict) -> None:
    if "properties" in left or "properties" in right:
        result["properties"] = _properties(left.get("properties", {}), right.get("properties", {}))
    if "required" in left or "required" in right:
        result["required"] = list(
            dict.fromkeys([*left.get("required", []), *right.get("required", [])])
        )
    if left.get("additionalProperties") is False or right.get("additionalProperties") is False:
        result["additionalProperties"] = False


def _compatible_types(left: Any, right: Any) -> bool:
    return not left or not right or left == right or {left, right} == {"number", "integer"}


def _properties(left: dict, right: dict) -> dict:
    return {
        key: intersect(left[key], right[key]) if key in left and key in right else value
        for key, value in {**left, **right}.items()
    }


def _bound(result: dict, left: dict, right: dict, key: str, select: Any) -> None:
    if key in left and key in right:
        result[key] = select(left[key], right[key])


def _finite(result: dict, left: dict, right: dict) -> dict | Literal[False]:
    choices = None
    for node in (left, right):
        available = [node["const"]] if "const" in node else node.get("enum")
        if available is not None:
            choices = available
            break
    if choices is None:
        return result
    accepted = [value for value in choices if _accepts(value, left) and _accepts(value, right)]
    if not accepted:
        return False
    result.pop("const", None)
    result["enum"] = accepted
    return result


def _accepts(value: Any, node: dict) -> bool:
    if "const" in node and (type(value), value) != (type(node["const"]), node["const"]):
        return False
    if "enum" in node and not any(
        (type(value), value) == (type(item), item) for item in node["enum"]
    ):
        return False
    expected = node.get("type")
    types = {"null": type(None), "string": str, "boolean": bool, "integer": int}
    if expected in types and type(value) is not types[expected]:
        return False
    if isinstance(value, str):
        return bool(node.get("minLength", 0) <= len(value) <= node.get("maxLength", len(value)))
    return True
