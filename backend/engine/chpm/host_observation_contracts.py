"""Allowlisted observations of an NPC's own state at a completed host boundary."""

import json
from typing import Annotated, Literal

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from backend.core.text_evidence import EvidenceSpan
from backend.engine.chpm.core.contracts import Contract, Identifier
from backend.engine.physical_conditions.schema import MAX_ACTIVE, MAX_RESOLVED, Kind, Status
from backend.engine.scene_staging.schema import Placement, Posture

MAX_SCENE_CHARS = 1200


def scene_view_size(data: dict) -> int:
    """Reserve a full identifier so copying cannot invalidate an otherwise packed view."""
    encoded = json.dumps(data, ensure_ascii=False)
    identifier = json.dumps(data["source_message_id"], ensure_ascii=False)
    return len(encoded) + max(0, 102 - len(identifier))


class SceneFact(Contract):
    id: Identifier
    subject_id: Identifier
    kind: Literal["environment", "process", "effect"]
    detail: str = Field(min_length=1, max_length=400)
    status: Literal["active", "ended", "unconfirmed", "needs_confirmation"]
    recorded_minute: int = Field(ge=0)
    updated_minute: int = Field(ge=0)
    cause_id: str = Field(default="", max_length=100)


class Possession(Contract):
    id: Identifier
    name: str = Field(default="", max_length=160)


class PhysicalFact(Contract):
    id: Identifier
    target_id: Identifier
    kind: Kind
    part: str = Field(min_length=1, max_length=80)
    detail: str = Field(min_length=1, max_length=320)
    status: Status


class CharacterPose(Contract):
    entity_id: Identifier
    posture: Posture | None = None
    placement: Placement | None = None


class PlacedItem(Contract):
    item_id: Identifier
    owner_id: Identifier
    name: str = Field(max_length=160)
    spatial_position: str = Field(min_length=1, max_length=120)


class ObservedSceneAction(Contract):
    actor_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=6)
    quote: str = Field(min_length=4, max_length=800)
    evidence_span: EvidenceSpan


class ObservedScene(Contract):
    source_message_id: Identifier
    source_revision_id: str | None = Field(default=None, max_length=100)
    source_hash: str = Field(min_length=64, max_length=64)
    scene_id: Identifier
    recorded_minute: int | None = Field(default=None, ge=0)
    meaning: Literal["last_completed_frame_not_ongoing"] = "last_completed_frame_not_ongoing"
    actions: tuple[ObservedSceneAction, ...] = Field(min_length=1, max_length=4)
    omitted_actions: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def bounded(self) -> "ObservedScene":
        if scene_view_size(self.model_dump(mode="json")) > MAX_SCENE_CHARS:
            raise ValueError("The observed scene exceeds its shared context budget.")
        return self


class HostFacts(Contract):
    scene_id: Identifier
    visible_actor_ids: tuple[Identifier, ...] = Field(default=(), max_length=128)
    owned_items: tuple[Possession, ...] | None = Field(default=None, max_length=256)
    worn_item_ids: tuple[Identifier, ...] | None = Field(default=None, max_length=32)
    last_observed_scene: ObservedScene | None = None
    physical_conditions: tuple[PhysicalFact, ...] | None = Field(
        default=None, max_length=MAX_ACTIVE + MAX_RESOLVED
    )
    scene_facts: tuple[SceneFact, ...] | None = Field(default=None, max_length=64)
    character_poses: tuple[CharacterPose, ...] | None = Field(default=None, max_length=128)
    placed_items: tuple[PlacedItem, ...] | None = Field(default=None, max_length=256)
    staging_omissions: (
        dict[Literal["character_poses", "placed_items"], Annotated[int, Field(ge=1)]] | None
    ) = Field(default=None, max_length=2)

    @model_validator(mode="after")
    def scene_matches(self) -> "HostFacts":
        if self.last_observed_scene and self.last_observed_scene.scene_id != self.scene_id:
            raise ValueError("An observed scene belongs to another room.")
        return self

    @model_serializer(mode="wrap")
    def serialize(self, handler: SerializerFunctionWrapHandler) -> dict:
        result: dict = handler(self)
        # Old source IDs and evidence roots hash the complete facts dictionary.
        # Unknown/legacy data must keep its exact shape; () is a known empty view.
        for field in (
            "physical_conditions",
            "last_observed_scene",
            "scene_facts",
            "character_poses",
            "placed_items",
            "staging_omissions",
        ):
            if getattr(self, field) is None:
                result.pop(field, None)
        return result
