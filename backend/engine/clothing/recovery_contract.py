"""Bind recovery's existing-item branch to real, owned garments, not arbitrary strings."""

from types import GenericAlias
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from backend.engine.clothing.profiles import garment_for_item
from backend.engine.clothing.recovery_schema import (
    ExistingRecoveryAction,
    NewRecoveryAction,
    RecoveryEntry,
    RecoveryProposal,
)
from backend.engine.clothing.schema import Garment
from backend.engine.narrated_items.schema import ItemAction
from backend.engine.visual_novel.continuity import Possessions


def existing_garments(context: dict) -> dict:
    snapshot = context["snapshot"]
    return {
        key: item
        for key, item in snapshot.items.items()
        if snapshot.owners.get(key) == context["actor"]["id"] and garment_for_item(item) is not None
    }


def response_schema(context: dict) -> type[BaseModel]:
    identifiers = tuple(existing_garments(context))
    action_type: Any = NewRecoveryAction
    if identifiers:
        existing = create_model(
            "OwnedRecoveryAction",
            __base__=ExistingRecoveryAction,
            item_id=(
                Literal[identifiers],
                Field(description="Exact owned garment ID; choose from enum."),
            ),
        )
        action_type = NewRecoveryAction | existing
    entry = create_model("BoundRecoveryEntry", __base__=RecoveryEntry, action=(action_type, ...))
    return create_model(
        "RecoveryProposal",
        __base__=RecoveryProposal,
        entries=(GenericAlias(list, entry), Field(default_factory=list, max_length=16)),
    )


def resolve_garment(action: ItemAction, snapshot: Possessions, actor_id: str) -> Garment:
    if action.new_item is not None:
        garment = action.new_item.clothing
        if action.new_item.kind != "clothing" or garment is None:
            raise ValueError(
                f"{action.new_item.name}: new recovery items require kind=clothing and garment metadata."
            )
        return garment
    item_id = action.item_id or ""
    item = snapshot.items.get(item_id)
    if item is None:
        raise ValueError(
            f"Unknown garment ID '{item_id}'. New garments require new_item; never invent an item_id."
        )
    label = f"{item.get('name', item_id)} [{item_id}]"
    if snapshot.owners.get(item_id) != actor_id:
        raise ValueError(f"{label}: the canonical owner is not the target NPC.")
    garment = garment_for_item(item)
    if garment is None:
        raise ValueError(
            f"{label}: this existing item has missing or invalid clothing metadata. Repair its metadata; do not create a duplicate."
        )
    return garment
