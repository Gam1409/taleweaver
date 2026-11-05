"""Strict JSON transport: tolerate an outer fence, never ambiguous objects or IDs."""

import json
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def response_schema(schema: type[BaseModel], identifiers: dict[str, list[str]] | None) -> dict:
    contract = schema.model_json_schema()
    _bind_ids(contract, identifiers or {})
    return contract


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
            nullable = any(
                option.get("type") == "null" for option in properties[key].get("anyOf", [])
            )
            properties[key]["enum"] = [*allowed, None] if nullable else allowed
            properties[key]["description"] = (
                "Copy an exact machine ID from this enum, never a display name."
            )
    for child in node.values():
        _bind_ids(child, identifiers)


def parse(schema: type[T], text: str) -> T:
    lines = text.strip().splitlines()
    if len(lines) >= 3 and lines[0] in {"```json", "```"} and lines[-1] == "```":
        text = "\n".join(lines[1:-1])
    value = json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_invalid_number)
    if not isinstance(value, dict):
        raise ValueError("CHPM needs one JSON object.")
    return schema.model_validate(value)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key in CHPM response.")
        result[key] = value
    return result


def _invalid_number(value: str) -> None:
    raise ValueError("Non-finite JSON value in CHPM response.")
