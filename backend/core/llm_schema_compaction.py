"""Share exact schema subtrees without interpreting literal JSON or changing reference scope."""

import json
import re
from collections.abc import Callable, Iterator
from copy import deepcopy
from functools import partial
from typing import Any

_MAPS = {
    "properties",
    "$defs",
    "definitions",
    "patternProperties",
    "dependentSchemas",
    "dependencies",
}
_ARRAYS = {"anyOf", "allOf", "oneOf", "prefixItems"}
_SINGLE = {
    "items",
    "additionalItems",
    "additionalProperties",
    "contains",
    "not",
    "propertyNames",
    "if",
    "then",
    "else",
    "contentSchema",
}
_SCOPE = {
    "$id",
    "id",
    "$anchor",
    "$dynamicAnchor",
    "$dynamicRef",
    "$recursiveAnchor",
    "$recursiveRef",
    "unevaluatedProperties",
    "unevaluatedItems",
}


def _children(node: dict) -> Iterator[tuple[tuple[str | int, ...], Any]]:
    for key, value in node.items():
        if key in _MAPS and isinstance(value, dict):
            for name, child in value.items():
                if isinstance(child, (dict, bool)):
                    yield (key, name), child
        elif key in _ARRAYS or key == "items" and isinstance(value, list):
            if isinstance(value, list):
                for index, child in enumerate(value):
                    yield (key, index), child
        elif key in _SINGLE and isinstance(value, (dict, bool)):
            yield (key,), value


def _container_cycle(value: Any) -> bool:
    active: set[int] = set()
    done: set[int] = set()
    pending = [(value, False)]
    while pending:
        item, leaving = pending.pop()
        if not isinstance(item, (dict, list, tuple)):
            continue
        key = id(item)
        if leaving:
            active.remove(key)
            done.add(key)
            continue
        if key in active:
            return True
        if key in done:
            continue
        active.add(key)
        pending.append((item, True))
        pending.extend(
            (child, False) for child in (item.values() if isinstance(item, dict) else item)
        )
    return False


def schema_nodes(
    schema: Any, path: str = "", *, opaque_keywords: frozenset[str] = frozenset()
) -> Iterator[tuple[str, dict]]:
    """Yield schema JSON Pointers; property names and annotation values stay opaque."""
    if not isinstance(schema, dict):
        return
    yield path, schema
    for tokens, child in _children(schema):
        if tokens[0] in opaque_keywords:
            continue
        suffix = "/".join(str(token).replace("~", "~0").replace("/", "~1") for token in tokens)
        yield from schema_nodes(child, path + "/" + suffix, opaque_keywords=opaque_keywords)


def map_schema(schema: Any, visit: Callable[[dict], dict]) -> Any:
    """Apply a transform only at schema positions, copying all other JSON verbatim."""
    if not isinstance(schema, dict) or _container_cycle(schema):
        return deepcopy(schema)
    result = deepcopy(schema)
    for tokens, child in _children(schema):
        parent = result
        for token in tokens[:-1]:
            parent = parent[token]
        parent[tokens[-1]] = map_schema(child, visit)
    return visit(result)


def safe_to_share(schema: dict) -> bool:
    """Scoped, unresolved and recursive schemas retain their original representation."""
    if _container_cycle(schema):
        return False
    definitions = schema.get("$defs", {})
    if not isinstance(definitions, dict):
        return False
    for _, node in schema_nodes(schema):
        if _SCOPE.intersection(node):
            return False
        if "$ref" not in node:
            continue
        reference = node["$ref"]
        if not isinstance(reference, str) or _target(reference, definitions) is None:
            return False
    return not _reference_cycle(definitions)


def _target(reference: str, definitions: dict) -> str | None:
    if not reference.startswith("#/$defs/"):
        return None
    token = reference[len("#/$defs/") :]
    # Relocating a definition can change a pointer into its original descendants.
    if "/" in token or "%" in token or re.search(r"~(?![01])", token):
        return None
    name = token.replace("~1", "/").replace("~0", "~")
    return name if name in definitions else None


def _reference_cycle(definitions: dict) -> bool:
    edges = {
        name: {
            _target(node["$ref"], definitions) for _, node in schema_nodes(value) if "$ref" in node
        }
        for name, value in definitions.items()
    }
    active: set[str] = set()
    done: set[str] = set()
    for name in edges:
        pending = [(name, False)]
        while pending:
            current, leaving = pending.pop()
            if leaving:
                active.remove(current)
                done.add(current)
                continue
            if current in active:
                return True
            if current in done:
                continue
            active.add(current)
            pending.append((current, True))
            pending.extend(
                (child, False) for child in edges.get(current, set()) if child is not None
            )
    return False


def _signature(node: dict) -> str:
    return json.dumps(
        node, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def _replace(node: dict, *, signature: str, reference: dict) -> dict:
    return reference if _signature(node) == signature else node


def _short_reference(node: dict, *, references: dict[str, str]) -> dict:
    if "$ref" in node:
        node["$ref"] = references[node["$ref"]]
    return node


def _short_definitions(schema: dict) -> dict:
    names = {name: f"d{index:x}" for index, name in enumerate(schema.get("$defs", {}))}
    if not names:
        return schema
    references = {
        "#/$defs/" + name.replace("~", "~0").replace("/", "~1"): f"#/$defs/{alias}"
        for name, alias in names.items()
    }
    result = map_schema(schema, partial(_short_reference, references=references))
    result["$defs"] = {names[name]: value for name, value in result["$defs"].items()}
    return result if len(_signature(result)) < len(_signature(schema)) else schema


def share_schema(schema: dict, *, short_names: bool = False) -> dict:
    """Share exact subtrees, optionally shortening safe local definition handles."""
    result = deepcopy(schema)
    if not safe_to_share(schema):
        return result
    for index in range(64):
        counts: dict[str, tuple[dict, int]] = {}
        for _, node in schema_nodes(result):
            key = _signature(node)
            _, count = counts.get(key, (node, 0))
            counts[key] = node, count + 1
        name = f"_s{index:x}"
        while name in result.get("$defs", {}):
            name += "_"
        reference = {"$ref": f"#/$defs/{name}"}
        cost = len(_signature(reference))
        ranked = [
            (len(key) * (count - 1) - cost * count - len(name) - 4, key, value)
            for key, (value, count) in counts.items()
            if count > 1
        ]
        if not ranked:
            break
        benefit, signature, original = max(ranked, key=lambda item: (item[0], item[1]))
        if benefit <= 0:
            break
        result = map_schema(
            result,
            partial(_replace, reference=reference, signature=signature),
        )
        result.setdefault("$defs", {})[name] = original
    return _short_definitions(result) if short_names else result
