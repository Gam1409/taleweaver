"""Allowlisted observations of an NPC's own state at a completed host boundary."""

from pydantic import Field

from backend.engine.chpm.core.contracts import Contract, Identifier


class Possession(Contract):
    id: Identifier
    name: str = Field(default="", max_length=160)


class HostFacts(Contract):
    scene_id: Identifier
    visible_actor_ids: tuple[Identifier, ...] = Field(default=(), max_length=128)
    owned_items: tuple[Possession, ...] | None = Field(default=None, max_length=256)
    worn_item_ids: tuple[Identifier, ...] | None = Field(default=None, max_length=32)
