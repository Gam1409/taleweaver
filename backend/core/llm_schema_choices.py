"""Eliminate impossible ID choices without allowing invented references."""

from copy import deepcopy
from typing import Any, Literal


def prune_unavailable(schema: dict) -> dict:
    """An empty allowlist disables its operation, rather than emitting `enum: []`."""
    body = deepcopy(schema)
    definitions = body.pop("$defs", {})
    unavailable: set[str] = set()
    while True:
        discovered = {
            f"#/$defs/{name}"
            for name, value in definitions.items()
            if _prune(value, unavailable) is False
        }
        if discovered <= unavailable:
            break
        unavailable |= discovered
    result = _prune(body, unavailable)
    if result is False:
        raise ValueError("Structured output has no valid operation with the available identifiers.")
    retained = {
        name: _prune(value, unavailable)
        for name, value in definitions.items()
        if f"#/$defs/{name}" not in unavailable
    }
    if retained:
        result["$defs"] = retained
    return result


def _prune(value: Any, unavailable: set[str]) -> dict | Literal[False]:
    if isinstance(value, bool):
        return {} if value else False
    node: dict = deepcopy(value)
    if node.get("enum") == [] or node.get("$ref") in unavailable:
        return False
    for keyword in ("anyOf", "oneOf", "allOf"):
        if keyword not in node:
            continue
        branches = [_prune(child, unavailable) for child in node[keyword]]
        if not any(branch is not False for branch in branches):
            return False
        if keyword == "allOf" and any(branch is False for branch in branches):
            return False
        node[keyword] = [branch for branch in branches if branch is not False]
    if not _properties(node, unavailable) or not _items(node, unavailable):
        return False
    return node


def _properties(node: dict, unavailable: set[str]) -> bool:
    properties = node.get("properties", {})
    required = set(node.get("required", []))
    for key, value in list(properties.items()):
        child = _prune(value, unavailable)
        if child is not False:
            properties[key] = child
            continue
        if key in required:
            return False
        if node.get("additionalProperties") is not False:
            raise ValueError("An unavailable optional reference requires a closed object schema.")
        del properties[key]
    additional = node.get("additionalProperties")
    if isinstance(additional, dict):
        node["additionalProperties"] = _prune(additional, unavailable)
    if "propertyNames" in node and _prune(node["propertyNames"], unavailable) is False:
        if required or node.get("minProperties", 0) > 0:
            return False
        node.update(properties={}, additionalProperties=False, maxProperties=0)
        del node["propertyNames"]
    return True


def _items(node: dict, unavailable: set[str]) -> bool:
    if "items" not in node or isinstance(node["items"], list):
        return True
    child = _prune(node["items"], unavailable)
    if child is not False:
        node["items"] = child
        return True
    if node.get("minItems", 0) > 0:
        return False
    # A valid, unused item type avoids grammar converters visiting a false schema.
    node.update(items={"type": "null"}, maxItems=0)
    return True
