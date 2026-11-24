"""Encode finite object cardinality for KoboldCpp's JSON-to-GBNF converter."""

from itertools import combinations
from math import comb
from typing import cast

from backend.core.llm_schema_compaction import map_schema

_MAX_KEYS = 7
_MAX_BRANCHES = 96
_OBJECT_KEYS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "propertyNames",
    "minProperties",
    "maxProperties",
}


def project_cardinality(schema: dict) -> dict:
    return cast(dict, map_schema(schema, _finite_object))


def _finite_object(node: dict) -> dict:
    properties = node.get("properties")
    if (
        node.get("type") != "object"
        or node.get("additionalProperties") is not False
        or not isinstance(properties, dict)
        or not 0 < len(properties) <= _MAX_KEYS
        or node.keys() - _OBJECT_KEYS
        or not {"minProperties", "maxProperties"}.intersection(node)
    ):
        return node
    required = node.get("required", [])
    if not isinstance(required, list) or not all(
        isinstance(key, str) and key in properties for key in required
    ):
        return node
    optional = [key for key in properties if key not in required]
    required_count = len(set(required))
    lower = node.get("minProperties", 0)
    upper = node.get("maxProperties", len(properties))
    if type(lower) is not int or type(upper) is not int or not 0 <= lower <= upper:
        return node
    sizes = range(max(0, lower - required_count), min(len(optional), upper - required_count) + 1)
    count = sum(comb(len(optional), size) for size in sizes)
    if not 0 < count <= _MAX_BRANCHES or count == 2 ** len(optional):
        return node
    branches = [
        _branch(properties, {*required, *keys})
        for size in sizes
        for keys in combinations(optional, size)
    ]
    # Retain any key-name predicate for standard JSON Schema validators.
    return {"anyOf": branches, **{k: node[k] for k in ("propertyNames",) if k in node}}


def _branch(properties: dict, keys: set[str]) -> dict:
    selected = {key: value for key, value in properties.items() if key in keys}
    return {
        "type": "object",
        "properties": selected,
        "required": list(selected),
        "additionalProperties": False,
    }
