"""User-reviewed recovery of missing garments; previews never mutate possessions."""

import asyncio
import logging
import shlex
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError
from backend.core.llm_deadlines import role_timeout
from backend.core.llm_router import GameMasterLLM
from backend.core.state_rejection_trace import reject
from backend.engine.clothing.context import detail_settings
from backend.engine.clothing.recovery_context import KEY, recovery_context
from backend.engine.clothing.recovery_contract import (
    response_schema,
)
from backend.engine.clothing.recovery_evaluation import evaluate, evaluated_preview
from backend.engine.clothing.recovery_mentions import (
    mention_checks,
    unreviewed_feedback,
)
from backend.engine.clothing.recovery_payload import build_payload
from backend.engine.clothing.recovery_prompt import PROMPT
from backend.engine.clothing.recovery_request import ProposalReview, request_proposal
from backend.engine.clothing.recovery_schema import RecoveryProposal
from backend.engine.clothing.recovery_selection import selected_entries
from backend.engine.clothing.runtime import _store_actor

logger = logging.getLogger(__name__)


def _preview_options(args: str) -> tuple[str, str, str]:
    arguments = shlex.split(args)[1:]
    if not 1 <= len(arguments) <= 3:
        raise ValueError('Expected wardrobe_preview NPC_ID [complex|small] ["search focus"].')
    role = arguments[1] if len(arguments) >= 2 else "complex"
    if role not in {"small", "complex"}:
        raise ValueError("Choose the complex or small recovery model.")
    focus = arguments[2].strip() if len(arguments) == 3 else ""
    if len(focus) > 400:
        raise ValueError("Recovery search focus must be at most 400 characters.")
    return arguments[0], role, focus


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
        npc_id, role, focus = _preview_options(args)
    except ValueError as exc:
        return f"DEBUG ERROR: {exc}"
    deadline = role_timeout(user, role)
    context = None
    model_step_started = False
    try:
        context = await recovery_context(db, state, avatar, npc_id)
        context["recovery_focus"] = focus
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
        preview = {
            "npc_id": npc_id,
            "token": str(uuid4()),
            "fingerprint": context["fingerprint"],
            **evaluated_preview(context, proposal, detailed, state.session_id),
            "model_role": role,
            "notes": proposal.notes,
            "messages_scanned": len(context["messages"]),
            "limited": context["limited"],
            "context_messages": len(context["messages"]),
            "model_step_started": True,
        }
        if preview["errors"] or preview["rejected_entries"] or preview["skipped"]:
            reject(
                "debug_item_recovery",
                "proposal_rejected",
                "Recovery proposals were rejected or skipped.",
                npc_id=npc_id,
                preview=preview,
                proposal=proposal,
            )
        elif focus and not proposal.entries:
            reject(
                "debug_item_recovery",
                "focused_recovery_unconfirmed",
                "The focused recovery request returned no candidate.",
                npc_id=npc_id,
                focus=focus,
                notes=proposal.notes,
                preview=preview,
            )
        await db.refresh(state)
        state.entity_states = {**(state.entity_states or {}), KEY: preview}
        return f"DEBUG: Wardrobe preview ready: {len(preview['accepted'])} proposed changes. Review and apply in Debug > NPCs > Clothing. Nothing has been added yet."
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
    reject(
        "debug_item_recovery",
        "preview_failed",
        message,
        npc_id=npc_id,
        model_role=role,
        model_step_started=model_step_started,
    )
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
        reject(
            "debug_item_recovery",
            "apply_revalidation_failed",
            "Selected changes failed revalidation.",
            proposal=preview.get("proposal"),
            selected=selected,
            accepted=accepted,
            expected=expected,
            errors=errors,
            skipped=skipped,
        )
        return "DEBUG ERROR: Selected changes failed revalidation; nothing was applied."
    states = dict(state.entity_states or {})
    _store_actor(SimpleNamespace(state=state, avatar=avatar), states, actors[preview["npc_id"]])
    states.pop(KEY, None)
    state.entity_states = states
    return f"DEBUG: Recovered {len(accepted)} clothing or placed-item records for {actors[preview['npc_id']]['name']}."
