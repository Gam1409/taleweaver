"""Small output contracts that assemble into the existing world schema."""

from copy import deepcopy
from types import GenericAlias
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from backend.engine.personality.generation import GeneratedNPCSchema
from backend.engine.world_schemas import (
    AwardTemplateSchema,
    ProtagonistSchema,
    QuestSchema,
    SequenceSchema,
    WorldExitSchema,
    WorldManifesto,
    WorldObjectSchema,
    WorldSceneSchema,
    WorldScriptSchema,
)

DETAIL_SCHEMAS = {
    "scenes": WorldSceneSchema,
    "npcs": GeneratedNPCSchema,
    "objects": WorldObjectSchema,
    "sequences": SequenceSchema,
    "quests": QuestSchema,
    "awards": AwardTemplateSchema,
    "scripts": WorldScriptSchema,
}

# Keep top-level compatibility fields in one authoritative schema. Descriptions
# and defaults are copied, so later additions to WorldManifesto are not lost.
_foundation_fields: dict[str, Any] = {
    name: (field.annotation, deepcopy(field))
    for name, field in WorldManifesto.model_fields.items()
    if name not in {*DETAIL_SCHEMAS, "exits", "protagonist"}
}
Foundation = create_model(
    "WorldFoundation",
    __config__=ConfigDict(extra="forbid"),
    **_foundation_fields,
)


class Seed(BaseModel):
    """A compact canonical entry, frozen once the plan is accepted."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=200)
    summary: str = Field(
        min_length=1,
        max_length=1200,
        description="Canonical facts, purpose, relationships and private knowledge; concise prose.",
    )
    start_scene_id: str = Field(default="", description="For NPCs and objects: planned scene ID.")
    owner_id: str = Field(
        default="",
        description="For objects: PROTAGONIST, NPC ID, container ID, or empty for a loose object.",
    )
    item_type: Literal[
        "",
        "CONSUMABLE",
        "WEARABLE",
        "STATIC",
        "COMBINABLE",
        "CONSTRUCTABLE",
        "PICKABLE",
        "WEAPON",
        "TOOL",
        "KEY",
        "READABLE",
        "CONTAINER",
        "SWITCH",
    ] = Field(default="", description="Required for object seeds; empty for other categories.")


class _WorldPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    foundation: BaseModel
    protagonist: Seed
    scenes: list[Seed] = Field(min_length=1)
    exits: list[WorldExitSchema]
    npcs: list[Seed]
    objects: list[Seed]
    sequences: list[Seed] = Field(max_length=15)
    quests: list[Seed]
    awards: list[Seed]
    scripts: list[Seed]


WorldPlan = create_model("WorldPlan", __base__=_WorldPlan, foundation=(Foundation, ...))


class ProtagonistDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protagonist: ProtagonistSchema


def batch_schema(kind: str) -> type[BaseModel]:
    """Only the current entity category's schema reaches the detail model."""
    return create_model(
        f"World{kind.title()}Batch",
        __config__=ConfigDict(extra="forbid"),
        items=(GenericAlias(list, DETAIL_SCHEMAS[kind]), ...),
    )
