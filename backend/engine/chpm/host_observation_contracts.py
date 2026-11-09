"""Allowlisted observations of an NPC's own state at a completed host boundary."""

from typing import Literal

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer

from backend.engine.chpm.core.contracts import Contract, Identifier
from backend.engine.physical_conditions.schema import MAX_ACTIVE, MAX_RESOLVED, Kind, Status


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


class HostFacts(Contract):
    scene_id: Identifier
    visible_actor_ids: tuple[Identifier, ...] = Field(default=(), max_length=128)
    owned_items: tuple[Possession, ...] | None = Field(default=None, max_length=256)
    worn_item_ids: tuple[Identifier, ...] | None = Field(default=None, max_length=32)
    physical_conditions: tuple[PhysicalFact, ...] | None = Field(
        default=None, max_length=MAX_ACTIVE + MAX_RESOLVED
    )
    scene_facts: tuple[SceneFact, ...] | None = Field(default=None, max_length=64)

    @model_serializer(mode="wrap")
    def serialize(self, handler: SerializerFunctionWrapHandler) -> dict:
        result: dict = handler(self)
        # Old source IDs and evidence roots hash the complete facts dictionary.
        # Unknown/legacy data must keep its exact shape; () is a known empty view.
        if self.physical_conditions is None:
            result.pop("physical_conditions", None)
        if self.scene_facts is None:
            result.pop("scene_facts", None)
        return result
