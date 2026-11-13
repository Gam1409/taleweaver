"""Reconcile completed VN item actions before staging and illustration snapshots."""

import asyncio
import hashlib
import json
import logging
from typing import Any

from backend.core.engine_detailed_trace import step
from backend.core.llm_deadlines import role_timeout
from backend.core.llm_router import GameMasterLLM
from backend.core.state_rejection_trace import reject
from backend.engine.character_identity import identity_facts
from backend.engine.clothing.context import actor_records, detail_settings
from backend.engine.clothing.runtime import _store_actor
from backend.engine.clothing.visuals import session_objects
from backend.engine.narrated_items import (
    coverage,
    evidence,
    independent_state,
    reference_schema,
    response_sections,
)
from backend.engine.narrated_items.apply import apply_actions
from backend.engine.narrated_items.context import actor_context, item_context
from backend.engine.narrated_items.diagnostics import describe_failure
from backend.engine.narrated_items.errors import ItemFailure
from backend.engine.narrated_items.observation_sources import verified_sources
from backend.engine.narrated_items.preflight import SkippedCheck, skipped_check
from backend.engine.narrated_items.schema import INSTRUCTIONS, ItemExtraction, SharedItemExtraction
from backend.engine.narrated_movement import runtime as narrated_movement
from backend.engine.narrated_movement.schema import INSTRUCTIONS as MOVEMENT_INSTRUCTIONS
from backend.engine.physical_conditions import runtime as physical_conditions
from backend.engine.physical_conditions.presentation import context as condition_context
from backend.engine.physical_conditions.prompts import INSTRUCTIONS as CONDITION_INSTRUCTIONS
from backend.engine.physical_conditions.scope import ItemScope, item_scope
from backend.engine.scene_continuity import runtime as scene_continuity
from backend.engine.scene_continuity.prompts import INSTRUCTIONS as SCENE_INSTRUCTIONS
from backend.engine.scene_staging import shared as shared_staging
from backend.engine.scene_staging.schema import SHARED_INSTRUCTIONS as STAGING_INSTRUCTIONS
from backend.engine.turn_replay.transactions import release_for_model
from backend.engine.visual_novel.continuity import PLAYER, SCENE, possession_snapshot

logger = logging.getLogger(__name__)
KEY = "__narrated_items__"
MAX_NARRATION = 16000
MAX_CONTEXT = 64000


def _status(
    manager: Any,
    message_id: str,
    narration: str,
    status: str,
    *,
    handled: bool = False,
    **details: Any,
) -> None:
    if (
        status in {"failed", "needs_review"}
        or details.get("rejected")
        or details.get("state_updates_rejected")
    ):
        reject(
            "items_and_shared_state",
            str(details.get("reason_code") or status),
            str(
                details.get("reason")
                or "State extraction contains rejected or unconfirmed changes."
            ),
            message_id=message_id,
            narration=narration,
            audit=details,
        )
    previous = (manager.state.entity_states or {}).get(KEY) or {}
    processed = previous.get("processed_message_ids", [])
    if status == "complete" or handled:
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


def _identified_actors(manager: Any, rows: list[Any]) -> dict:
    actors = actor_records(manager, rows)
    identities = {
        PLAYER: manager.avatar,
        **{row.id: row for row in rows if row.entity_type == "NPC"},
    }
    for identifier, actor in actors.items():
        actor.update(identity_facts(identities[identifier]))
    return actors


async def _condition_scope(
    manager: Any, pending: physical_conditions.Pending, rows: list[Any], snapshot: Any, scene: dict
) -> ItemScope:
    pending.player_message = await physical_conditions.player_report(
        manager, str(getattr(manager, "_vn_player_message_id", "") or "")
    )
    scope = item_scope(manager, rows, snapshot=snapshot, visible=scene.get("public_subjects", []))
    pending.item_targets = set(scope.item_ids)
    return scope


@step("items.scene.conditions.reconcile")
async def reconcile_items(
    manager: Any,
    narration: str,
    *,
    completed: bool,
    resolution: str,
    blocked: bool = False,
    blocked_reason: str = "",
    blocked_targets: set[str] | None = None,
) -> list[str]:
    physical_conditions.discard(manager)
    manager._pending_scene_continuity = None
    manager._pending_narrated_movement = None
    message_id = str(getattr(manager, "_vn_player_message_id", "") or "")
    ledger = (manager.state.entity_states or {}).get(KEY) or {}
    staging_enabled = shared_staging.begin(
        manager,
        narration,
        reuse=(
            message_id in ledger.get("processed_message_ids", [])
            and ledger.get("source_hash") == hashlib.sha256(narration.encode()).hexdigest()
        ),
    )
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
    independent_allowed = (
        skipped is not None
        and skipped.reason_code == "rules_rejected"
        and blocked_targets is not None
    )
    if skipped is not None and (
        (not staging_enabled and not independent_allowed) or skipped.reason_code != "rules_rejected"
    ):
        pending_conditions.error = skipped.reason
        _status(manager, message_id, narration, "needs_review", **skipped.details())
        return [skipped.message()]
    rows = await session_objects(manager.db, manager.state.session_id)
    actors = _identified_actors(manager, rows)
    snapshot = possession_snapshot(manager, rows)
    scene_context = await scene_continuity.prepare(manager)
    scope = await _condition_scope(manager, pending_conditions, rows, snapshot, scene_context)
    catalog = evidence.Catalog(
        narration,
        str(scene_context.get("scene_description", "")),
        scope=f"{manager.state.session_id}:{message_id}:{manager.state.current_scene_id}",
    )
    scene_context = {**scene_context, "scene_description": catalog.room_passages}
    payload = json.dumps(
        {
            "completed_narration": catalog.narration_passages,
            "extraction_coverage_groups": coverage.groups(catalog),
            "player_actor_id": PLAYER,
            "scene_source_id": SCENE,
            "authoritative_resolution": resolution,
            "player_report": pending_conditions.player_message[1]
            if pending_conditions.player_message
            else "",
            "actors": actor_context(actors),
            "items": item_context(snapshot.items),
            **(
                {"item_state_targets": item_context(scope.additional_items)}
                if scope.additional_items
                else {}
            ),
            "owners": snapshot.owners,
            "movement_context": await narrated_movement.prepare(manager, rows, narration),
            "detailed_clothing": detail_settings(manager)["detailed"],
            "physical_conditions": condition_context(
                manager.state, set(actors) | set(scope.item_ids)
            ),
            "scene_continuity": scene_context,
            "scene_staging": shared_staging.prepare(manager, actors, rows),
            "item_changes_allowed": skipped is None,
            "independent_state_scope": {
                "blocked_subject_ids": sorted(blocked_targets | {manager.state.current_scene_id})
            }
            if independent_allowed and blocked_targets is not None
            else None,
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
                INSTRUCTIONS
                + CONDITION_INSTRUCTIONS
                + SCENE_INSTRUCTIONS
                + MOVEMENT_INSTRUCTIONS
                + independent_state.INSTRUCTIONS
                + (STAGING_INSTRUCTIONS if staging_enabled else ""),
                payload,
                SharedItemExtraction,
                llm.model,
                game_id=manager.game_id,
                operation="narrated_items",
                phase="reconciliation",
                response_schema=reference_schema.build(
                    SharedItemExtraction if staging_enabled else ItemExtraction,
                    catalog,
                    complete=True,
                ),
            ),
            timeout=role_timeout(manager.user, "small"),
        )
        sections = response_sections.read(result, staging=staging_enabled)
        original_actions = result.actions if isinstance(result, ItemExtraction) else None
        result, sections = coverage.annotate(result, catalog, sections, staging=staging_enabled)
        result = evidence.bind(result, narration, catalog=catalog)
        shared_staging.propose(manager, result, unconfirmed_sections=sections.staging_missing)
        extraction, schema_failures, batch_denied, source_indices = independent_state.unpack(
            result, actors, original_actions=original_actions
        )
        failures = list(schema_failures)
        changed, accepted, errors = (
            (actors, [], [])
            if skipped
            else apply_actions(
                extraction,
                actors,
                snapshot,
                narration,
                detailed=detail_settings(manager)["detailed"],
                session_id=manager.state.session_id,
                message_id=message_id,
                failures=failures,
                source_indices=source_indices,
                verified_sources=await verified_sources(manager, extraction, actors),
            )
        )
        errors = [failure.message() for failure in schema_failures] + errors
        denied = set(blocked_targets or ()) | set(batch_denied or ())
        state_rejected = 0
        if denied:
            extraction, state_rejected = independent_state.select(
                manager, extraction, denied, set(actors) | set(scope.item_ids)
            )
        narrated_movement.complete(
            manager,
            extraction.movements,
            denied=denied,
            confirmed=skipped is None and "movements" in sections.provided,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Completed item reconciliation failed for session %s", manager.game_id)
        failure = describe_failure(exc)
        if skipped is not None:
            _status(
                manager,
                message_id,
                narration,
                "needs_review",
                **skipped.details(),
                staging_failure=failure.payload(),
            )
            return [skipped.message()]
        _status(
            manager,
            message_id,
            narration,
            "failed",
            error_type=type(exc).__name__,
            failure=failure.payload(),
        )
        return [failure.message()]
    return _finish_extraction(
        manager,
        extraction,
        pending_conditions,
        changed,
        accepted,
        errors,
        snapshot,
        message_id,
        narration,
        failures,
        skipped,
        independent_allowed,
        state_rejected,
        sections,
    )


def _finish_extraction(
    manager: Any,
    extraction: ItemExtraction,
    pending_conditions: Any,
    changed: dict,
    accepted: list[dict],
    errors: list[str],
    snapshot: Any,
    message_id: str,
    narration: str,
    failures: list[ItemFailure],
    skipped: SkippedCheck | None,
    independent_allowed: bool,
    state_rejected: int,
    sections: response_sections.Sections,
) -> list[str]:
    _store_changes(manager, changed, accepted, snapshot.catalog)
    shared_staging.approve_items(manager, accepted)
    if skipped is None or independent_allowed:
        if "condition_updates" in sections.provided:
            pending_conditions.complete(
                extraction.condition_updates,
                set(changed) | pending_conditions.item_targets,
                item_targets=pending_conditions.item_targets,
            )
        else:
            pending_conditions.error = "The shared response did not confirm condition_updates."
        scene_continuity.complete(
            manager,
            extraction.scene_updates,
            extraction.final_frame_actions,
            unconfirmed_sections=sections.scene_missing,
        )
    if skipped is not None:
        if not independent_allowed:
            pending_conditions.error = skipped.reason
        _status(
            manager,
            message_id,
            narration,
            "needs_review",
            **skipped.details(),
            state_updates_rejected=state_rejected,
            **sections.details(),
        )
        return [skipped.message(), *_state_review(state_rejected), *sections.messages()]
    _status(
        manager,
        message_id,
        narration,
        "needs_review" if sections.needs_review else "complete",
        handled=True,
        accepted=accepted,
        rejected=errors,
        rejected_details=[failure.payload() for failure in failures],
        state_updates_rejected=state_rejected,
        **sections.details(),
    )
    messages = [
        f"{changed[entry['destination_owner']]['name']}: {entry['item']['name']} ({entry['disposition']})."
        for entry in accepted
    ]
    if errors:
        messages.append(
            "Some narrated item changes need review and were not applied: " + " ".join(errors)
        )
    messages.extend(_state_review(state_rejected))
    messages.extend(sections.messages())
    return messages


def _state_review(rejected: int) -> list[str]:
    return (
        [
            "Some physical or scene changes need review: independence from rejected item changes could not be confirmed."
        ]
        if rejected
        else []
    )


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
