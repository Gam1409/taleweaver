"""Canonical semantic guidance alongside native structural decoding, without a second full schema."""

import json
from copy import deepcopy

from backend.core.llm_provider_config import JSON_SCHEMA_INSTRUCTION
from backend.core.llm_request_tuning import compact_json_schema
from backend.core.llm_schema_compaction import safe_to_share, schema_nodes

_ANNOTATIONS = {
    "description",
    "default",
    "examples",
    "discriminator",
    "format",
    "deprecated",
    "readOnly",
    "writeOnly",
    "contentEncoding",
    "contentMediaType",
}
_DEFERRED = {
    "pattern",
    "uniqueItems",
    "minProperties",
    "maxProperties",
    "oneOf",
    "allOf",
    "prefixItems",
}
_STRUCTURAL = {
    "$schema",
    "$defs",
    "$ref",
    "title",
    "type",
    "properties",
    "required",
    "additionalProperties",
    "propertyNames",
    "items",
    "anyOf",
    "const",
    "enum",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minItems",
    "maxItems",
    "not",
    "if",
    "then",
    "else",
    "contains",
    "minContains",
    "maxContains",
    "patternProperties",
    "dependentRequired",
    "dependentSchemas",
}
_HEADER = (
    "\n\nReturn one JSON object using the requested native schema. "
    "Do not translate JSON keys or add Markdown. Canonical schema field guidance and "
    "local validation rules, indexed by schema JSON Pointer ('' is the root):\n"
)


def guidance(schema: dict, local_checks: tuple[str, ...] = ()) -> str:
    """Preserve opaque annotations and every rule not fully supplied by native decoding."""
    nodes = list(schema_nodes(schema)) if safe_to_share(schema) else []
    unknown = set(local_checks) - _DEFERRED
    if (
        not nodes
        or unknown
        or any(set(node) - _STRUCTURAL - _ANNOTATIONS - _DEFERRED for _, node in nodes)
    ):
        return JSON_SCHEMA_INSTRUCTION.format(
            schema_json=json.dumps(compact_json_schema(schema), separators=(",", ":"))
        )
    notes = {
        path: {
            key: deepcopy(value) for key, value in node.items() if key in _ANNOTATIONS | _DEFERRED
        }
        for path, node in schema_nodes(schema, opaque_keywords=frozenset(_DEFERRED))
        if _ANNOTATIONS.union(_DEFERRED).intersection(node)
    }
    return _HEADER + json.dumps(notes, separators=(",", ":")) if notes else ""
