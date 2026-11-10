"""Bind exact source occurrences before the existing independent domain validators."""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from backend.core.text_passages import index
from backend.engine.narrated_items.schema import SharedItemExtraction
from backend.engine.narrated_items.source_catalog import Catalog

__all__ = ["Catalog", "bind", "bind_staging", "passages", "remap", "stamp"]


def passages(narration: str) -> dict[str, str]:
    """Legacy narration-only aliases remain available to existing local callers."""
    return {"passage:" + key: text for key, text in index(narration).items()}


def bind(result: Any, narration: str, *, catalog: Catalog | None = None) -> Any:
    body = result.model_dump() if isinstance(result, BaseModel) else deepcopy(result)
    if not isinstance(body, dict):
        return result
    if catalog is None:
        return _legacy(result, body, narration)
    for field in ("actions", "condition_updates", "scene_updates", "final_frame_actions"):
        _section(body.get(field), catalog, allow_room=field == "scene_updates")
    staging = body.get("staging")
    if isinstance(staging, dict):
        for field in ("changes", "props", "explicit"):
            _section(staging.get(field), catalog, allow_room=False)
    # Independent candidate validation also applies when optional staging is off.
    return SharedItemExtraction.model_validate(body)


def bind_staging(result: Any, catalog: Catalog) -> Any:
    from backend.engine.scene_staging.proposals import StagingProposal

    body = result.model_dump() if isinstance(result, BaseModel) else deepcopy(result)
    if not isinstance(body, dict):
        return result
    for field in ("changes", "props", "explicit"):
        _section(body.get(field), catalog, allow_room=False)
    return StagingProposal.model_validate(body)


def _section(entries: Any, catalog: Catalog, *, allow_room: bool) -> None:
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry.pop("evidence_span", None)  # Offsets are host-owned, never model assertions.
        value = entry.get("evidence")
        try:
            if not isinstance(value, str):
                raise ValueError("Evidence must select a source occurrence.")
            selected = (
                catalog.resolve(value, allow_room=allow_room)
                if value.startswith(("narration:", "room:", "passage:"))
                else catalog.literal(value, allow_room=allow_room)
            )
            entry["evidence"] = selected.quote
            entry["evidence_span"] = selected.span.model_dump()
            if allow_room:
                entry["source"] = selected.kind
        except ValueError:
            # No source was resolved. Keep the candidate for the existing per-entry
            # rejection path, including unconfirming only its affected pose actor.
            entry["evidence"] = None


def _legacy(result: Any, body: dict, narration: str) -> Any:
    available = passages(narration)
    for field in ("actions", "condition_updates"):
        entries = body.get(field)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            value = entry.get("evidence") if isinstance(entry, dict) else None
            if isinstance(value, str) and value not in narration:
                text = available.get(value)
                if text is not None and len(text) >= 4:
                    entry["evidence"] = text
    return type(result).model_validate(body) if isinstance(result, BaseModel) else body


def remap(states: dict, message_ids: dict[str, str]) -> dict:
    """Copied checks retain local source IDs; missing history never borrows a quote."""
    from backend.engine.narrated_items.runtime import KEY

    result = deepcopy(states)
    ledger = result.get(KEY)
    if not isinstance(ledger, dict):
        return result
    old_id = ledger.get("message_id")
    ledger["message_id"] = message_ids.get(old_id, "") if isinstance(old_id, str) else ""
    processed = ledger.get("processed_message_ids")
    ledger["processed_message_ids"] = [
        message_ids[key]
        for key in (processed if isinstance(processed, list) else [])
        if isinstance(key, str) and key in message_ids
    ]
    source = ledger.get("narration_source")
    if isinstance(source, dict):
        old_id = source.get("message_id")
        source["message_id"] = message_ids.get(old_id) if isinstance(old_id, str) else None
        if source["message_id"] is None:
            source["available"] = False
    return result


def stamp(manager: Any, message: Any) -> None:
    """Complete the existing item check's provenance after its assistant row is saved."""
    from backend.engine.narrated_items.runtime import KEY
    from backend.engine.scene_staging.state import digest

    states = manager.state.entity_states or {}
    ledger = states.get(KEY)
    if not isinstance(ledger, dict):
        return
    if (
        ledger.get("source_hash") != digest(message.content)
        or ledger.get("message_id") != getattr(manager, "_vn_player_message_id", None)
        or ledger.get("narration_source")
    ):
        return
    proof = {
        "message_id": message.id,
        "revision_id": message.revision_id,
        "content_hash": digest(message.content),
    }
    manager.state.entity_states = {**states, KEY: {**ledger, "narration_source": proof}}
