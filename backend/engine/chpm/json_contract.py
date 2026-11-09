"""Strict JSON transport: tolerate an outer fence, never ambiguous objects or IDs."""

import json
from copy import deepcopy
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def response_schema(
    schema: type[BaseModel],
    identifiers: dict[str, list[str]] | None,
    *,
    explicit_keys: bool = False,
) -> dict:
    contract = schema.model_json_schema()
    _bind_ids(contract, identifiers or {})
    if explicit_keys:
        _explicit_enum_maps(contract)
    _strip_titles(contract)
    return contract


def _explicit_enum_maps(node: Any) -> None:
    """Grammar backends can ignore propertyNames; finite keys need real properties."""
    if isinstance(node, list):
        for child in node:
            _explicit_enum_maps(child)
        return
    if not isinstance(node, dict):
        return
    names = node.get("propertyNames", {}).get("enum")
    values = node.get("additionalProperties")
    if (
        node.get("type") == "object"
        and isinstance(names, list)
        and all(isinstance(key, str) for key in names)
        and isinstance(values, dict)
        and "properties" not in node
    ):
        node["properties"] = {key: deepcopy(values) for key in names}
        node["additionalProperties"] = False
    for child in node.values():
        _explicit_enum_maps(child)


def _strip_titles(node: Any) -> None:
    """Remove generated display labels, never schema constraints or property names."""
    if isinstance(node, list):
        for child in node:
            _strip_titles(child)
        return
    if not isinstance(node, dict):
        return
    node.pop("title", None)
    for group in ("properties", "$defs"):
        for child in node.get(group, {}).values():
            _strip_titles(child)
    for keyword in ("items", "anyOf", "allOf", "oneOf", "additionalProperties"):
        _strip_titles(node.get(keyword))


def _bind_ids(node: Any, identifiers: dict[str, list[str]]) -> None:
    if isinstance(node, list):
        for child in node:
            _bind_ids(child, identifiers)
        return
    if not isinstance(node, dict):
        return
    properties = node.get("properties", {})
    for key, allowed in identifiers.items():
        if key in properties:
            if properties[key].get("type") == "array":
                properties[key]["items"] = {**properties[key].get("items", {}), "enum": allowed}
                continue
            if properties[key].get("type") == "object":
                properties[key]["propertyNames"] = {"enum": allowed}
                continue
            null_only = properties[key].get("type") == "null"
            nullable = null_only or any(
                option.get("type") == "null" for option in properties[key].get("anyOf", [])
            )
            properties[key]["enum"] = (
                [None] if null_only else [*allowed, None] if nullable else allowed
            )
    for child in node.values():
        _bind_ids(child, identifiers)


def parse(schema: type[T], text: str) -> T:
    return schema.model_validate(decode(text))


def decode(text: str) -> dict:
    """Retain only complete, unambiguous objects for a possible proposal repair."""
    lines = text.strip().splitlines()
    if len(lines) >= 3 and lines[0] in {"```json", "```"} and lines[-1] == "```":
        text = "\n".join(lines[1:-1])
    value = json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_invalid_number)
    if not isinstance(value, dict):
        raise ValueError("CHPM needs one JSON object.")
    return value


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key in CHPM response.")
        result[key] = value
    return result


def _invalid_number(value: str) -> None:
    raise ValueError("Non-finite JSON value in CHPM response.")
