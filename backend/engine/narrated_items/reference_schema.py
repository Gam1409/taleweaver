"""Narrow this request's wire citations without changing canonical saved models."""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from backend.engine.narrated_items.coverage import groups
from backend.engine.narrated_items.source_catalog import Catalog

RANGE_DESCRIPTION = (
    "A pN..pN+1 reference supplies the exact contiguous text of two adjacent occurrences. "
    "Only its first occurrence pN anchors coverage; independent later changes need their own proposal."
)


def build(model: type[BaseModel], catalog: Catalog, *, complete: bool = False) -> dict:
    schema = citation_schema(model, catalog)
    if complete:
        schema["required"] = list(schema["properties"])
    definitions = schema.setdefault("$defs", {})
    keys = groups(catalog)
    tags = [
        "items",
        "conditions",
        "scene",
        "unchanged",
        "historical",
        "uncertain",
        "conditions_deferred",
    ]
    if "staging" in schema["properties"]:
        tags.append("staging")
    schema["properties"]["coverage"] = {
        "type": "object",
        "properties": {
            key: {
                "type": "array",
                "items": {"enum": tags},
                "minItems": 1,
                "maxItems": 5 if "staging" in schema["properties"] else 4,
                "uniqueItems": True,
            }
            for key in keys
        },
        "required": list(keys),
        "additionalProperties": False,
    }
    staging = definitions.get("SceneExtraction")
    if complete and isinstance(staging, dict):
        staging["required"] = ["changes", "props", "explicit"]
    return schema


def citation_schema(model: type[BaseModel], catalog: Catalog) -> dict:
    """Reuse the same request-scoped proof contract for bounded correction patches."""
    schema = deepcopy(model.model_json_schema())
    definitions = schema.setdefault("$defs", {})
    definitions["NarrationEvidenceReference"] = {
        "type": "string",
        "enum": catalog.references(include_ranges=True),
        "description": RANGE_DESCRIPTION,
    }
    definitions["VisualEvidenceReference"] = {
        "type": "string",
        "enum": catalog.references(minimum=3, include_ranges=True),
        "description": RANGE_DESCRIPTION,
    }
    definitions["SceneEvidenceReference"] = {
        "type": "string",
        "enum": catalog.references(allow_room=True, include_ranges=True),
        "description": RANGE_DESCRIPTION,
    }
    for name in (
        "ExistingItemAction",
        "NewItemAction",
        "ConditionProposal",
        "Action",
        "MovementProposal",
    ):
        _citations(definitions.get(name), "NarrationEvidenceReference")
    for name in ("SceneDelta", "ExplicitDelta", "PropDelta"):
        _citations(definitions.get(name), "VisualEvidenceReference")
    update = definitions.get("Update")
    if isinstance(update, dict):
        _citations(update, "SceneEvidenceReference")
        update["properties"].pop("source", None)
        update["required"] = [key for key in update.get("required", []) if key != "source"]
        # The canonical authored-source/kind rule runs after host source binding.
        update.pop("allOf", None)
    return schema


def _citations(schema: Any, definition: str) -> None:
    if isinstance(schema, dict) and "evidence" in schema.get("properties", {}):
        schema["properties"]["evidence"] = {"$ref": "#/$defs/" + definition}
