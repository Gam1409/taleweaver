"""Reconcile completed VN item actions before staging and illustration snapshots."""

import asyncio
import hashlib
import json
import logging
from typing import Any

from backend.core.llm_deadlines import role_timeout
from backend.core.llm_router import GameMasterLLM
from backend.engine.character_identity import identity_facts
from backend.engine.clothing.context import actor_records, detail_settings
from backend.engine.clothing.runtime import _store_actor
from backend.engine.clothing.visuals import session_objects
from backend.engine.narrated_items.apply import apply_actions
from backend.engine.narrated_items.context import actor_context, item_context
from backend.engine.narrated_items.diagnostics import describe_failure
from backend.engine.narrated_items.errors import ItemFailure
from backend.engine.narrated_items.preflight import skipped_check
from backend.engine.narrated_items.schema import INSTRUCTIONS, ItemExtraction
from backend.engine.physical_conditions import runtime as physical_conditions
from backend.engine.physical_conditions.presentation import context as condition_context
from backend.engine.physical_conditions.prompts import INSTRUCTIONS as CONDITION_INSTRUCTIONS
from backend.engine.turn_replay.transactions import release_for_model
from backend.engine.visual_novel.continuity import PLAYER, SCENE, possession_snapshot

logger = logging.getLogger(__name__)
KEY = "__narrated_items__"
MAX_NARRATION = 16000
MAX_CONTEXT = 64000


def _status(manager: Any, message_id: str, narration: str, status: str, **details: Any) -> None:
    previous = (manager.state.entity_states or {}).get(KEY) or {}
    processed = previous.get("processed_message_ids", [])
    if status == "complete":
        processed = [*processed, message_id][-128:]
    manager.state.entity_states = {
        **(manager.state.entity_states or {}),
        KEY: {
            "processed_message_ids": processed,
            "message_id": message_id,
            "source_hash": hashlib.sha256(narration.encode()).hexdigest(),
            "scene_id": getattr(manager.state, "current_scene_id", None),
            "status": status,
            **details,
        },
    }


async def reconcile_items(
    manager: Any,
    narration: str,
    *,
    completed: bool,
    resolution: str,
    blocked: bool = False,
    blocked_reason: str = "",
) -> list[str]:
    physical_conditions.discard(manager)
    message_id = str(getattr(manager, "_vn_player_message_id", "") or "")
    ledger = (manager.state.entity_states or {}).get(KEY) or {}
    if (
        not completed
        or not message_id
        or not narration.strip()
        or message_id in ledger.get("processed_message_ids", [])
    ):
        return []
    pending_conditions = physical_conditions.stage(
        manager, [], set(), error="The shared item/state check did not complete."
    )
    skipped = skipped_check(
        narration, blocked=blocked, blocked_reason=blocked_reason, limit=MAX_NARRATION
    )
    if skipped is not None:
        pending_conditions.error = skipped.reason
        _status(manager, message_id, narration, "needs_review", **skipped.details())
        return [skipped.message()]
    rows = await session_objects(manager.db, manager.state.session_id)
    actors = actor_records(manager, rows)
    identities = {
        PLAYER: manager.avatar,
        **{row.id: row for row in rows if row.entity_type == "NPC"},
    }
    for identifier, actor in actors.items():
        actor.update(identity_facts(identities[identifier]))
    snapshot = possession_snapshot(manager, rows)
    detailed = detail_settings(manager)["detailed"]
    payload = json.dumps(
        {
            "completed_narration": narration,
            "player_actor_id": PLAYER,
            "scene_source_id": SCENE,
            "authoritative_resolution": resolution,
            "actors": actor_context(actors),
            "items": item_context(snapshot.items),
            "owners": snapshot.owners,
            "detailed_clothing": detailed,
            "physical_conditions": condition_context(
                manager.state, set(actors) | set(snapshot.items)
            ),
        },
        ensure_ascii=False,
    )
    if len(payload) > MAX_CONTEXT:
        _status(
            manager,
            message_id,
            narration,
            "needs_review",
            reason="Item context exceeds text budget.",
            actor_count=len(actors),
            item_count=len(snapshot.items),
            context_characters=len(payload),
        )
        return ["Item reconciliation needs review; the available item context is too large."]
    await release_for_model(manager)
    try:
        llm = GameMasterLLM.for_role(manager.user, "small")
        result = await asyncio.wait_for(
            llm.aexecute_complex_task(
                INSTRUCTIONS + CONDITION_INSTRUCTIONS,
                payload,
                ItemExtraction,
                llm.model,
                game_id=manager.game_id,
                operation="narrated_items",
                phase="reconciliation",
            ),
            timeout=min(60, role_timeout(manager.user, "small")),
        )
        extraction = ItemExtraction.model_validate(result)
        failures: list[ItemFailure] = []
        changed, accepted, errors = apply_actions(
            extraction,
            actors,
            snapshot,
            narration,
            detailed=detailed,
            session_id=manager.state.session_id,
            message_id=message_id,
            failures=failures,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Completed item reconciliation failed for session %s", manager.game_id)
        failure = describe_failure(exc)
        _status(
            manager,
            message_id,
            narration,
            "failed",
            error_type=type(exc).__name__,
            failure=failure.payload(),
        )
        return [failure.message()]
    _store_changes(manager, changed, accepted, snapshot.catalog)
    pending_conditions.complete(extraction.condition_updates, set(actors) | set(snapshot.items))
    _status(
        manager,
        message_id,
        narration,
        "complete",
        accepted=accepted,
        rejected=errors,
        rejected_details=[failure.payload() for failure in failures],
    )
    messages = [
        f"{changed[entry['destination_owner']]['name']}: {entry['item']['name']} ({entry['disposition']})."
        for entry in accepted
    ]
    if errors:
        messages.append(
            "Some narrated item changes need review and were not applied: " + " ".join(errors)
        )
    return messages


def _store_changes(manager: Any, changed: dict, accepted: list[dict], catalog: dict) -> None:
    states = dict(manager.state.entity_states or {})
    affected = {entry[key] for entry in accepted for key in ("source_owner", "destination_owner")}
    for identifier in affected - {SCENE}:
        _store_actor(manager, states, changed[identifier])
    for entry in accepted:
        identifier = entry["item"]["id"]
        if identifier not in catalog:
            continue
        states[identifier] = {
            **states.get(identifier, {}),
            "is_in_inventory": True,
            "current_scene_id": manager.state.current_scene_id,
            "vn_item_data": entry["item"],
        }
    manager.state.entity_states = states
