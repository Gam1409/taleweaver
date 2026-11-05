"""User-reviewed recovery of missing garments; previews never mutate possessions."""

import asyncio
import logging
import shlex
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError
from backend.core.llm_deadlines import role_timeout
from backend.core.llm_router import GameMasterLLM
from backend.engine.clothing.context import detail_settings
from backend.engine.clothing.recovery_context import KEY, recovery_context
from backend.engine.clothing.recovery_contract import (
    resolve_garment,
    response_schema,
)
from backend.engine.clothing.recovery_evidence import evidence_issues, rejected_entry
from backend.engine.clothing.recovery_mentions import (
    mention_checks,
    unreviewed_feedback,
)
from backend.engine.clothing.recovery_payload import build_payload
from backend.engine.clothing.recovery_policy import classify_action, partition_rejections
from backend.engine.clothing.recovery_prompt import PROMPT
from backend.engine.clothing.recovery_request import ProposalReview, request_proposal
from backend.engine.clothing.recovery_schema import RecoveryEntry, RecoveryProposal
from backend.engine.clothing.recovery_selection import selected_entries
from backend.engine.clothing.runtime import _store_actor
from backend.engine.narrated_items.apply import apply_actions
from backend.engine.narrated_items.errors import ItemFailure
from backend.engine.narrated_items.schema import ItemAction, ItemExtraction

logger = logging.getLogger(__name__)


def _source_error(source: dict, source_id: str, action: ItemAction, actor_id: str) -> str:
    if not source:
        return f"Source {source_id}: no matching assistant narration."
    if action.source_owner != actor_id or action.destination_owner != actor_id:
        return "Wrong owner: recovery only accepts the target NPC's own garments."
    return ""


def evaluate(
    context: dict,
    proposal: RecoveryProposal,
    detailed: bool,
    session_id: str,
    *,
    diagnostics: list[dict] | None = None,
    selected_indices: set[int] | None = None,
) -> tuple:
    actor = context["actor"]
    actors = {actor["id"]: actor}
    snapshot = deepcopy(context["snapshot"])
    rejected_details = diagnostics if diagnostics is not None else []
    accepted: list[dict] = []
    errors = []
    skipped = []
    sources = {row["id"]: row for row in context["messages"] if row["role"] == "assistant"}
    entries = [
        (index, entry)
        for index, entry in enumerate(proposal.entries)
        if selected_indices is None or index in selected_indices
    ]
    for index, entry in entries:
        action = classify_action(entry.action)
        label = action.new_item.name if action.new_item else str(action.item_id)
        source = sources.get(entry.source_message_id, {})
        source_error = _source_error(source, entry.source_message_id, action, actor["id"])
        if source_error:
            errors.append(f"{label}: {source_error}")
            rejected_details.append(rejected_entry(index, entry, label, [source_error]))
            continue
        try:
            garment = resolve_garment(action, snapshot, actor["id"])
        except ValueError as exc:
            errors.append(str(exc))
            rejected_details.append(rejected_entry(index, entry, label, [str(exc)]))
            continue
        issues = evidence_issues(entry, action, source, garment)
        if issues:
            errors.extend(f"{label}: {reason}" for reason in issues)
            rejected_details.append(rejected_entry(index, entry, label, issues, garment))
            continue
        failures: list[ItemFailure] = []
        changed, additions, _ = apply_actions(
            ItemExtraction(actions=[action]),
            actors,
            snapshot,
            source["content"],
            detailed=detailed,
            session_id=session_id,
            message_id=f"{entry.source_message_id}:wardrobe:{index}",
            failures=failures,
        )
        actors = changed
        blocking, omitted = partition_rejections(
            failures, detailed=detailed, age=actor.get("age_years")
        )
        errors.extend(blocking)
        if blocking:
            rejected_details.append(rejected_entry(index, entry, label, blocking, garment))
        skipped.extend(omitted)
        for addition in additions:
            addition["proposal_index"] = index
            _finish_addition(actors[actor["id"]], addition, entry)
            identifier = addition["item"]["id"]
            snapshot.items[identifier] = addition["item"]
            snapshot.owners[identifier] = actor["id"]
            snapshot.catalog[identifier] = addition["item"]
            accepted.append(addition)
    return actors, accepted, errors, list(dict.fromkeys(skipped))


def _finish_addition(actor: dict, addition: dict, entry: RecoveryEntry) -> None:
    addition["source_message_id"] = entry.source_message_id
    addition["uncovered_regions"] = list(dict.fromkeys(entry.uncovered_regions))
    addition["placement_evidence"] = entry.placement_evidence
    if entry.uncovered_regions:
        _set_partial_wear(actor, addition)
    # Keep real source IDs for checkpoint and regeneration provenance.
    for key in ("item_origin", "clothing_origin"):
        if key in addition["item"]:
            addition["item"][key]["source_message_id"] = entry.source_message_id
    identifier = addition["item"]["id"]
    for field in ("inventory", "resolved_inventory"):
        actor[field] = [
            addition["item"] if isinstance(row, dict) and row.get("id") == identifier else row
            for row in actor[field]
        ]


def _set_partial_wear(actor: dict, addition: dict) -> None:
    for worn in actor["visual_profile"]["worn"]:
        if worn["item_id"] == addition["item"]["id"]:
            worn["uncovered_regions"] = addition["uncovered_regions"]


def _review_proposal(
    result: BaseModel, context: dict, detailed: bool, session_id: str
) -> ProposalReview:
    proposal = RecoveryProposal.model_validate(result.model_dump())
    diagnostics: list[dict] = []
    _, _, errors, _ = evaluate(context, proposal, detailed, session_id, diagnostics=diagnostics)
    rejected = {row["index"] for row in diagnostics}
    preserved = [
        entry.model_dump() for index, entry in enumerate(proposal.entries) if index not in rejected
    ]
    errors.extend(unreviewed_feedback(mention_checks(context, proposal)))
    return ProposalReview(errors=errors, preserved_entries=preserved)


async def debug_wardrobe_preview(
    db: Any, state: Any, args: str, user: Any = None, adventure: Any = None, avatar: Any = None
) -> str:
    if not state.is_debug_enabled or avatar is None:
        return "DEBUG ERROR: Wardrobe recovery requires debug mode and a session avatar."
    try:
        arguments = shlex.split(args)[1:]
    except ValueError:
        return "DEBUG ERROR: Expected wardrobe_preview NPC_ID [complex|small]."
    if not 1 <= len(arguments) <= 2 or (
        len(arguments) == 2 and arguments[1] not in {"small", "complex"}
    ):
        return "DEBUG ERROR: Expected wardrobe_preview NPC_ID [complex|small]."
    npc_id = arguments[0]
    role = arguments[1] if len(arguments) == 2 else "complex"
    deadline = role_timeout(user, role)
    context = None
    model_step_started = False
    try:
        context = await recovery_context(db, state, avatar, npc_id)
        detailed = detail_settings(SimpleNamespace(state=state))["detailed"]
        llm = GameMasterLLM.for_role(user, role)
        context, payload = build_payload(context, detailed)
        await db.commit()
        model_step_started = True
        result = await asyncio.wait_for(
            request_proposal(
                llm,
                PROMPT,
                payload,
                response_schema(context),
                state.session_id,
                review=lambda value: _review_proposal(value, context, detailed, state.session_id),
            ),
            timeout=deadline,
        )
        proposal = RecoveryProposal.model_validate(result.model_dump())
        diagnostics: list[dict] = []
        _, accepted, errors, skipped = evaluate(
            context, proposal, detailed, state.session_id, diagnostics=diagnostics
        )
        preview = {
            "npc_id": npc_id,
            "token": str(uuid4()),
            "fingerprint": context["fingerprint"],
            "proposal": proposal.model_dump(),
            "accepted": accepted,
            "errors": errors,
            "skipped": skipped,
            "rejected_entries": diagnostics,
            "mention_checks": mention_checks(context, proposal),
            "rejected_sources": {
                row["id"]: row["content"]
                for row in context["messages"]
                if row["role"] == "assistant"
                and any(issue["source_message_id"] == row["id"] for issue in diagnostics)
            },
            "model_role": role,
            "notes": proposal.notes,
            "messages_scanned": len(context["messages"]),
            "limited": context["limited"],
            "context_messages": len(context["messages"]),
            "model_step_started": True,
        }
        await db.refresh(state)
        state.entity_states = {**(state.entity_states or {}), KEY: preview}
        return f"DEBUG: Wardrobe preview ready: {len(accepted)} proposed changes. Review and apply in Debug > NPCs > Clothing. Nothing has been added yet."
    except TimeoutError:
        message = (
            f"{role.capitalize()}-model request timed out (configured deadline: {deadline:g}s). "
            "No clothing was changed. Check the selected model server and its timeout in Intelligence settings."
        )
    except InferenceUncertainError:
        message = (
            "No recovery request was sent: completion of a previous model request is unconfirmed. "
            "In Administration > Intelligence > Inference queue, refresh and clear the stopped request "
            "only after verifying generation has stopped on the model server. No clothing was changed."
        )
    except InferenceQueueError:
        message = "No recovery request was sent: the inference queue is unavailable. Try again when it is free. No clothing was changed."
    except ValueError as exc:
        detail = str(exc).strip()[:500].rstrip(".") or type(exc).__name__
        message = f"Invalid recovery result: {detail}. No clothing was changed."
    except Exception as exc:
        logger.exception("Wardrobe recovery preview failed for %s", state.session_id)
        message = f"Wardrobe preview failed ({type(exc).__name__}). No clothing was changed. Check the model server and logs."
    state.entity_states = {
        **(state.entity_states or {}),
        KEY: {
            "npc_id": npc_id,
            "token": str(uuid4()),
            "accepted": [],
            "errors": [message],
            "notes": "Preview failed; no proposal is available to apply.",
            "messages_scanned": 0,
            "context_messages": len(context["messages"]) if context else 0,
            "model_step_started": model_step_started,
            "limited": context["limited"] if context else False,
        },
    }
    return f"DEBUG ERROR: {message}"


async def debug_wardrobe_apply(
    db: Any, state: Any, args: str, user: Any = None, adventure: Any = None, avatar: Any = None
) -> str:
    if not state.is_debug_enabled or avatar is None:
        return "DEBUG ERROR: Wardrobe recovery requires debug mode."
    preview = (state.entity_states or {}).get(KEY) or {}
    parts = args.split()
    if len(parts) not in {2, 3} or parts[1] != preview.get("token"):
        return "DEBUG ERROR: Preview is missing or has been replaced. Generate a new preview."
    try:
        selected = selected_entries(preview, parts[2] if len(parts) == 3 else None)
    except ValueError as exc:
        return f"DEBUG ERROR: {exc}"
    context = await recovery_context(db, state, avatar, preview["npc_id"])
    if context["fingerprint"] != preview.get("fingerprint"):
        return "DEBUG ERROR: Story or state changed after preview. Generate a new preview."
    detailed = detail_settings(SimpleNamespace(state=state))["detailed"]
    actors, accepted, errors, skipped = evaluate(
        context,
        RecoveryProposal.model_validate(preview["proposal"]),
        detailed,
        state.session_id,
        selected_indices=selected,
    )
    expected = [row for row in preview["accepted"] if row.get("proposal_index") in selected]
    if errors or skipped or not accepted or accepted != expected:
        return "DEBUG ERROR: Selected changes failed revalidation; nothing was applied."
    states = dict(state.entity_states or {})
    _store_actor(SimpleNamespace(state=state, avatar=avatar), states, actors[preview["npc_id"]])
    states.pop(KEY, None)
    state.entity_states = states
    return f"DEBUG: Recovered {len(accepted)} clothing records for {actors[preview['npc_id']]['name']}."
