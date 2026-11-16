"""Project a canonical contract onto portable structural decoder constraints.

The original contract remains in the prompt and local validators. Unsupported
text predicates are reported as local checks, never used to repair game facts.
"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from backend.core.llm_schema_choices import prune_unavailable
from backend.core.llm_schema_merge import SchemaProjectionError, intersect
from backend.core.llm_schema_values import json_equal


@dataclass(frozen=True)
class Projection:
    schema: dict
    local_checks: tuple[str, ...]


def project(schema: dict) -> Projection:
    local: set[str] = set()
    result = _node(prune_unavailable(schema), local)
    return Projection(prune_unavailable(result), tuple(sorted(local)))


def _node(value: Any, local: set[str]) -> Any:
    if isinstance(value, bool):
        return value
    node = deepcopy(value)
    for key in ("title", "description", "default", "examples", "discriminator"):
        node.pop(key, None)
    _predicates(node, local)
    _children(node, local)
    _tuple_items(node, local)
    if isinstance(node.get("type"), list):
        choices = node.pop("type")
        node = {"anyOf": [{**node, "type": choice} for choice in choices]}
    return _combinations(node, local)


def _predicates(node: dict, local: set[str]) -> None:
    pattern = node.pop("pattern", None)
    if pattern == r"^\s*$":
        node["const"] = ""
    elif pattern is not None:
        local.add("pattern")
    for key in ("uniqueItems", "minProperties", "maxProperties"):
        if key in node:
            local.add(key)


def _children(node: dict, local: set[str]) -> None:
    for key in ("properties", "$defs"):
        if key in node:
            node[key] = {name: _node(child, local) for name, child in node[key].items()}
    for key in ("items", "additionalProperties", "propertyNames"):
        if isinstance(node.get(key), dict):
            node[key] = _node(node[key], local)
    for key in ("prefixItems", "anyOf", "oneOf"):
        if key in node:
            node[key] = [_node(child, local) for child in node[key]]


def _tuple_items(node: dict, local: set[str]) -> None:
    prefix = node.pop("prefixItems", None)
    if prefix is None:
        return
    if not prefix or node.get("maxItems") != len(prefix):
        raise SchemaProjectionError("The tuple requires local positional validation.")
    if all(child == prefix[0] for child in prefix):
        node["items"] = prefix[0]
    else:
        node["items"] = {"anyOf": prefix}
        local.add("prefixItems")


def _combinations(node: dict, local: set[str]) -> dict:
    conditions = node.pop("allOf", [])
    definitions = node.pop("$defs", None)
    for keyword in ("oneOf", "anyOf"):
        if keyword not in node:
            continue
        if keyword == "oneOf":
            local.add("oneOf")
        branches = node.pop(keyword)
        node = {"anyOf": [intersect(node, branch) for branch in branches]}
    for condition in conditions:
        if "if" in condition:
            node = _conditional(node, condition, local)
        else:
            merged = intersect(node, _node(condition, local))
            if not isinstance(merged, dict):
                raise SchemaProjectionError(
                    "The projected structured output has no valid operation."
                )
            node = merged
    if definitions is not None:
        node["$defs"] = definitions
    return node


def _conditional(node: dict | bool, condition: dict, local: set[str]) -> dict:
    if not isinstance(node, dict):
        raise SchemaProjectionError("The conditional requires an object discriminator.")
    if "anyOf" in node:
        return {
            "anyOf": [
                _conditional(branch, condition, local)
                for branch in node["anyOf"]
                if branch is not False
            ]
        }
    field, expected = _discriminator(condition)
    properties = node.get("properties", {})
    if field not in properties and node.get("additionalProperties") is False:
        return node
    choices = _finite_choices(properties.get(field, {}))
    if not choices:
        raise SchemaProjectionError("The discriminator requires local schema validation.")
    branches = []
    for value in choices:
        branch = intersect(node, {"properties": {field: {"const": value}}})
        if json_equal(value, expected):
            branch = intersect(branch, {"required": [field]})
            branch = intersect(branch, _node(condition.get("then", {}), local))
        branches.append(branch)
    if field not in node.get("required", []) and all(
        json_equal(value, expected) for value in choices
    ):
        if node.get("additionalProperties") is not False:
            raise SchemaProjectionError(
                "An optional discriminator requires a closed object schema."
            )
        branches.append(intersect(node, {"properties": {field: False}}))
    return {"anyOf": branches}


def _discriminator(condition: dict) -> tuple[str, Any]:
    predicate = condition["if"]
    if (
        set(condition) - {"if", "then"}
        or not isinstance(predicate, dict)
        or set(predicate) != {"properties", "required"}
    ):
        raise SchemaProjectionError("The conditional requires local schema validation.")
    fields = predicate.get("properties", {})
    if not isinstance(fields, dict) or len(fields) != 1:
        raise SchemaProjectionError("The conditional requires local schema validation.")
    field, rule = next(iter(fields.items()))
    if not isinstance(rule, dict) or set(rule) != {"const"}:
        raise SchemaProjectionError("The conditional requires local schema validation.")
    if predicate.get("required") != [field]:
        raise SchemaProjectionError("The conditional requires a finite discriminator.")
    return field, rule["const"]


def _finite_choices(rule: dict | bool) -> list[Any]:
    if rule is False:
        return []
    if not isinstance(rule, dict):
        raise SchemaProjectionError("The conditional requires a finite discriminator.")
    if "const" in rule:
        return _scalar_choices([rule["const"]])
    if "enum" in rule:
        choices = rule["enum"]
        if not isinstance(choices, list):
            raise SchemaProjectionError("The conditional requires a finite discriminator.")
        return _scalar_choices(choices)
    if rule.get("type") == "null":
        return [None]
    if "anyOf" in rule:
        return [value for branch in rule["anyOf"] for value in _finite_choices(branch)]
    raise SchemaProjectionError("The conditional requires a finite discriminator.")


def _scalar_choices(choices: list[Any]) -> list[Any]:
    if any(type(value) not in {str, int, float, bool, type(None)} for value in choices):
        raise SchemaProjectionError("Composite discriminators require local schema validation.")
    return choices
