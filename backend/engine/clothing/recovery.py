"""User-reviewed recovery of missing garments; previews never mutate possessions."""

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.core.llm_router import GameMasterLLM
from backend.engine.clothing.context import detail_settings
from backend.engine.clothing.profiles import garment_for_item
from backend.engine.clothing.recovery_context import KEY, recovery_context
from backend.engine.clothing.runtime import _store_actor
from backend.engine.narrated_items.apply import apply_actions
from backend.engine.narrated_items.schema import INSTRUCTIONS, ItemAction, ItemExtraction

logger = logging.getLogger(__name__)


class RecoveryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_message_id: str
    action: ItemAction


class RecoveryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[RecoveryEntry] = Field(default_factory=list, max_length=6)
    notes: str = Field(default="", max_length=1200)


PROMPT = (
    INSTRUCTIONS
    + """
Return RecoveryProposal with entries and notes, not the live actions wrapper.
This is an explicit preview to recover missing clothing for target_actor from chronological history.
Read all messages in order. Only assistant narration establishes completed events; player text
provides context, not confirmation. Later removal, transfer, loss or destruction wins over earlier
wear descriptions. Return only garments still owned by target_actor at the end of the history.
A removed garment still owned by the NPC is carried, not worn. Never return transferred or lost
items. If current ownership or wear is uncertain, omit it and explain in notes. No implied underwear.
Each entry cites the exact source_message_id and contiguous evidence from that assistant message.
Use source_owner=destination_owner=target_actor.id. Only clothing, never ordinary items or rewards.
Existing canonical possessions override old prose. Reuse IDs; no translated or reworded duplicates.
This is additive recovery: preserve unspecified recorded clothes. Do not rewrite the existing outfit.
"""
)


def evaluate(context: dict, proposal: RecoveryProposal, detailed: bool, session_id: str) -> tuple:
    actor = context["actor"]
    actors = {actor["id"]: actor}
    snapshot = context["snapshot"]
    accepted: list[dict] = []
    errors = []
    sources = {row["id"]: row for row in context["messages"] if row["role"] == "assistant"}
    for entry in proposal.entries:
        action = entry.action
        source = sources.get(entry.source_message_id)
        if (
            not source
            or action.source_owner != actor["id"]
            or action.destination_owner != actor["id"]
        ):
            errors.append("Recovery requires the target NPC and an existing narration source.")
            continue
        garment = (
            action.new_item.clothing
            if action.new_item
            else garment_for_item(snapshot.items.get(action.item_id, {}))
        )
        if garment is None:
            errors.append("Recovery only accepts clothing with valid garment metadata.")
            continue
        changed, additions, rejected = apply_actions(
            ItemExtraction(actions=[action]),
            actors,
            snapshot,
            source["content"],
            detailed=detailed,
            session_id=session_id,
            message_id=f"{entry.source_message_id}:wardrobe:{len(accepted)}",
        )
        actors = changed
        errors.extend(rejected)
        for addition in additions:
            addition["source_message_id"] = entry.source_message_id
            # Keep real source IDs for checkpoint and regeneration provenance.
            for key in ("item_origin", "clothing_origin"):
                if key in addition["item"]:
                    addition["item"][key]["source_message_id"] = entry.source_message_id
            identifier = addition["item"]["id"]
            for field in ("inventory", "resolved_inventory"):
                actors[actor["id"]][field] = [
                    addition["item"]
                    if isinstance(row, dict) and row.get("id") == identifier
                    else row
                    for row in actors[actor["id"]][field]
                ]
            snapshot.items[identifier] = addition["item"]
            snapshot.owners[identifier] = actor["id"]
            snapshot.catalog[identifier] = addition["item"]
            accepted.append(addition)
    return actors, accepted, errors


async def debug_wardrobe_preview(
    db: Any, state: Any, args: str, user: Any = None, adventure: Any = None, avatar: Any = None
) -> str:
    if not state.is_debug_enabled or avatar is None:
        return "DEBUG ERROR: Wardrobe recovery requires debug mode and a session avatar."
    npc_id = args.partition(" ")[2].strip()
    try:
        context = await recovery_context(db, state, avatar, npc_id)
        llm = GameMasterLLM.for_role(user, "small")
        payload = json.dumps(
            {
                "target_actor": context["actor"],
                "history": context["messages"],
                "canonical_items": context["snapshot"].items,
                "owners": context["snapshot"].owners,
            },
            ensure_ascii=False,
        )
        if len(payload) > 64000:
            raise ValueError("Recovery context is too large; no changes were made.")
        await db.commit()
        result = await asyncio.wait_for(
            llm.aexecute_complex_task(
                PROMPT,
                payload,
                RecoveryProposal,
                llm.model,
                game_id=state.session_id,
                operation="wardrobe_recovery",
                phase="preview",
            ),
            timeout=60,
        )
        proposal = RecoveryProposal.model_validate(result)
        detailed = detail_settings(SimpleNamespace(state=state))["detailed"]
        _, accepted, errors = evaluate(context, proposal, detailed, state.session_id)
        preview = {
            "npc_id": npc_id,
            "token": str(uuid4()),
            "fingerprint": context["fingerprint"],
            "proposal": proposal.model_dump(),
            "accepted": accepted,
            "errors": errors,
            "notes": proposal.notes,
            "messages_scanned": len(context["messages"]),
            "limited": context["limited"],
        }
        await db.refresh(state)
        state.entity_states = {**(state.entity_states or {}), KEY: preview}
        return f"DEBUG: Wardrobe preview ready: {len(accepted)} proposed changes. Review and apply in Location and clothing. Nothing has been added yet."
    except (ValueError, TimeoutError) as exc:
        return f"DEBUG ERROR: Wardrobe preview failed: {exc}"
    except Exception as exc:
        logger.exception("Wardrobe recovery preview failed for %s", state.session_id)
        return f"DEBUG ERROR: Wardrobe preview failed ({type(exc).__name__}); nothing was applied."


async def debug_wardrobe_apply(
    db: Any, state: Any, args: str, user: Any = None, adventure: Any = None, avatar: Any = None
) -> str:
    if not state.is_debug_enabled or avatar is None:
        return "DEBUG ERROR: Wardrobe recovery requires debug mode."
    preview = (state.entity_states or {}).get(KEY) or {}
    if args.partition(" ")[2].strip() != preview.get("token"):
        return "DEBUG ERROR: Preview is missing or has been replaced. Generate a new preview."
    if preview.get("errors") or not preview.get("accepted"):
        return "DEBUG ERROR: Preview has rejected or empty changes; nothing was applied."
    context = await recovery_context(db, state, avatar, preview["npc_id"])
    if context["fingerprint"] != preview.get("fingerprint"):
        return "DEBUG ERROR: Story or state changed after preview. Generate a new preview."
    detailed = detail_settings(SimpleNamespace(state=state))["detailed"]
    actors, accepted, errors = evaluate(
        context, RecoveryProposal.model_validate(preview["proposal"]), detailed, state.session_id
    )
    if errors or not accepted or accepted != preview["accepted"]:
        return "DEBUG ERROR: Preview has rejected or empty changes; nothing was applied."
    states = dict(state.entity_states or {})
    _store_actor(SimpleNamespace(state=state, avatar=avatar), states, actors[preview["npc_id"]])
    states.pop(KEY, None)
    state.entity_states = states
    return f"DEBUG: Recovered {len(accepted)} clothing records for {actors[preview['npc_id']]['name']}."
