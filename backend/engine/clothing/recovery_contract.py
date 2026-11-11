"""Bind recovery's existing-item branch to real, owned garments, not arbitrary strings."""

from types import GenericAlias
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from backend.engine.clothing.profiles import attachment_item_allowed, garment_for_item
from backend.engine.clothing.recovery_schema import (
    ExistingRecoveryAction,
    ExistingRecoveryBodyAction,
    NewRecoveryAction,
    NewRecoveryBodyAction,
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
    action_type: Any = NewRecoveryAction | NewRecoveryBodyAction
    for name, base, identifiers in (
        ("OwnedRecoveryAction", ExistingRecoveryAction, tuple(existing_garments(context))),
        (
            "OwnedRecoveryBodyAction",
            ExistingRecoveryBodyAction,
            tuple(existing_body_items(context)),
        ),
    ):
        if not identifiers:
            continue
        existing = create_model(
            name,
            __base__=base,
            item_id=(
                Literal[identifiers],
                Field(description="Exact owned item ID; choose from enum."),
            ),
        )
        action_type = action_type | existing
    entry = create_model("BoundRecoveryEntry", __base__=RecoveryEntry, action=(action_type, ...))
    return create_model(
        "RecoveryProposal",
        __base__=RecoveryProposal,
        entries=(GenericAlias(list, entry), Field(default_factory=list, max_length=16)),
    )


def existing_body_items(context: dict) -> dict:
    snapshot = context["snapshot"]
    return {
        key: item
        for key, item in snapshot.items.items()
        if snapshot.owners.get(key) == context["actor"]["id"] and attachment_item_allowed(item)
    }


def resolve_recovery_item(
    action: ItemAction, snapshot: Possessions, actor_id: str
) -> Garment | None:
    if not action.attachment_slot:
        return resolve_garment(action, snapshot, actor_id)
    if action.new_item is not None:
        if action.new_item.kind != "ordinary":
            raise ValueError("New body-placement recovery requires an ordinary item.")
        return None
    item = snapshot.items.get(action.item_id or "")
    if item is None or snapshot.owners.get(action.item_id or "") != actor_id:
        raise ValueError("Body placement requires an existing item owned by the target NPC.")
    if not attachment_item_allowed(item):
        raise ValueError("This item cannot be recovered as a body attachment.")
    return garment_for_item(item)


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
