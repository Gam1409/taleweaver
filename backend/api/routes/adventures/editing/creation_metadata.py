"""Build entity creation metadata with the existing editor storage contracts."""

from typing import Any

from backend.api.routes.adventures.editing.common import _normalize_lock_fields
from backend.api.routes.adventures.editing.entity_update.item_metadata import (
    _validated_switch,
    update_item_events,
)
from backend.api.routes.adventures.editing.entity_update.npc import update_npc_events
from backend.api.routes.adventures.editing.schemas import EntityCreateRequest
from backend.engine.clothing.authoring import store_editor_clothing

_LOCK_FIELDS = ("code_to_unlock", "item_to_unlock", "rule_to_unlock")


def _normalize_container_lock(metadata: dict[str, Any]) -> None:
    if not any(field in metadata for field in (*_LOCK_FIELDS, "locked")):
        return
    code, item, rule = _normalize_lock_fields(
        code_to_unlock=metadata.get("code_to_unlock"),
        item_to_unlock=metadata.get("item_to_unlock"),
        rule_to_unlock=metadata.get("rule_to_unlock"),
    )
    metadata.update(code_to_unlock=code, item_to_unlock=item, rule_to_unlock=rule)
    locked = metadata.get("locked")
    metadata["locked"] = bool(locked if locked is not None else (code or item or rule))


def entity_creation_metadata(payload: EntityCreateRequest, item_type: str | None) -> dict[str, Any]:
    metadata = dict(payload.metadata_json or {})
    store_editor_clothing(metadata, payload)
    if payload.entity_type == "NPC":
        update_npc_events(metadata, payload)
        if payload.personality_profile is not None:
            metadata["personality_profile"] = payload.personality_profile.model_dump()
    else:
        update_item_events(metadata, payload)
    if item_type == "CONTAINER":
        _normalize_container_lock(metadata)
    if item_type == "SWITCH":
        metadata["switch"] = _validated_switch(metadata.get("switch") or {})
    return metadata
