"""One bounded Small-role proposal per VN input; no background agents or world edits."""

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import select

from backend.core.llm_router import GameMasterLLM
from backend.engine.memory_rag.prompts import recall_block
from backend.engine.visual_novel.prompts import FALLBACK_CONTEXT, SYSTEM_PROMPT, narrator_context
from backend.engine.visual_novel.schema import (
    MAX_ACTIVE,
    MAX_PROCESSED,
    CharacterState,
    InteractionPlan,
    SocialProposal,
    SocialState,
)
from backend.engine.visual_novel.state import (
    apply_event,
    ensure_character,
    load_state,
    mark_processed,
    save_state,
)
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity

logger = logging.getLogger(__name__)
PLANNING_TIMEOUT = 45
MAX_ACTION_CHARS = 4000
MAX_SCENE_CHARS = 4000


def _visible(npc: Any, state: Any) -> bool:
    overrides = (state.entity_states or {}).get(npc.id, {})
    if not isinstance(overrides, dict):
        overrides = {}
    scene = overrides.get("current_scene_id", npc.current_scene_id)
    hidden = overrides.get("is_hidden", npc.is_hidden)
    defeated = overrides.get("is_defeated", getattr(npc, "is_defeated", False))
    return scene == state.current_scene_id and not hidden and not defeated


async def _present_npcs(manager: Any, social: SocialState, user_msg: str) -> list[Any]:
    rows = await manager.db.scalars(
        select(WorldEntity).where(
            WorldEntity.session_id == manager.state.session_id,
            WorldEntity.entity_type == "NPC",
            WorldEntity.is_in_inventory.is_(False),
        )
    )
    present = [npc for npc in rows.all() if _visible(npc, manager.state)]

    def priority(npc: Any) -> tuple[bool, bool, str]:
        known = social.characters.get(npc.id)
        mentioned = bool(npc.name and npc.name.casefold() in user_msg.casefold())
        return (not mentioned, not bool(known and known.pinned), npc.id)

    return sorted(present, key=priority)[:MAX_ACTIVE]


async def _scene_evidence(manager: Any) -> tuple[str, str]:
    # Do not fish for an older matching scene after the player has just arrived.
    message = await manager.db.scalar(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == manager.state.session_id,
            ChatMessage.role == "assistant",
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    if message is None or message.scene_id != manager.state.current_scene_id:
        return "", ""
    return str(message.id), str(message.content or "")[-MAX_SCENE_CHARS:]


def _character_context(character: CharacterState) -> dict[str, Any]:
    # Persistence hashes and full ledgers are never useful model context.
    return {
        "core": character.core[:700],
        "goals": [goal[:700] for goal in character.goals],
        "relationship": character.relationship.model_dump(),
        "emotion": character.emotion,
        "next_intention": character.next_intention,
        "recent_memories_for_orientation_only": [
            {"event": memory.kind, "evidence": memory.evidence[:200]}
            for memory in character.memories[-3:]
        ],
    }


def _payload(
    social: SocialState,
    npcs: list[Any],
    user_msg: str,
    scene_context: str,
    history: list[dict],
    historical_recall: str = "",
) -> str:
    cast = [
        {
            "npc_id": npc.id,
            "name": npc.name,
            "authored_description": str(getattr(npc, "description", "") or "")[:700],
            "character": _character_context(social.characters[npc.id]),
        }
        for npc in npcs
        if npc.id in social.characters
    ]
    data = {
        "present_cast": cast,
        "player_action": user_msg[:MAX_ACTION_CHARS],
        "scene_context": scene_context[-MAX_SCENE_CHARS:],
        "historical_recall_untrusted_orientation_only": historical_recall,
        "history_for_orientation_only": [
            {"role": m.get("role"), "content": str(m.get("content", ""))[-400:]}
            for m in history[-2:]
            if isinstance(m, dict)
        ],
    }
    return json.dumps(data, ensure_ascii=False)


def apply_plan(
    social: SocialState,
    plan: InteractionPlan,
    npcs: list[Any],
    user_msg: str,
    scene_context: str,
    source_message_id: str,
) -> SocialState:
    """Mutate durable completed events; return a separate tentative narrator direction."""
    present = {npc.id for npc in npcs}
    sources = {"player_action": user_msg[:MAX_ACTION_CHARS], "scene_context": scene_context}

    def grounded(proposal: SocialProposal) -> bool:
        return (
            proposal.npc_id in present
            and proposal.npc_id in social.characters
            and proposal.basis == "performed_interaction"
            and proposal.evidence in sources[proposal.source]
        )

    if source_message_id and source_message_id not in social.reviewed_scene_message_ids:
        seen: set[str] = set()
        # Accept legacy scene observations, but never let a new player reaction
        # crowd out the completed interaction for the same NPC.
        completed = [*plan.completed_events, *plan.reactions]
        for proposal in completed:
            if (
                proposal.source != "scene_context"
                or proposal.npc_id in seen
                or not grounded(proposal)
            ):
                continue
            seen.add(proposal.npc_id)
            character = social.characters[proposal.npc_id]
            apply_event(social, character, proposal, source_message_id)
            # A witnessed emotion need not earn points or pass the positive-event
            # cooldown. It remains separate from scores, promotion and memories.
            _set_direction(character, proposal)
        social.reviewed_scene_message_ids = (
            social.reviewed_scene_message_ids + [source_message_id]
        )[-MAX_PROCESSED:]
    directed = social.model_copy(deep=True)
    seen = set()
    for proposal in plan.reactions:
        if proposal.source != "player_action" or proposal.npc_id in seen or not grounded(proposal):
            continue
        seen.add(proposal.npc_id)
        _set_direction(directed.characters[proposal.npc_id], proposal)
    return directed


def _set_direction(character: CharacterState, proposal: SocialProposal) -> None:
    character.emotion = proposal.emotion
    character.emotion_cause = proposal.evidence
    character.next_intention = proposal.intention


async def plan_interaction(
    manager: Any, user_msg: str, history: list[dict], game_event: Any
) -> str:
    """Caller commits alongside the turn; game_event is deliberately never mutated."""
    social = load_state(manager.state)
    message_id = str(getattr(manager, "_vn_player_message_id", "") or "")
    if social is None or not message_id or message_id in social.processed_message_ids:
        return FALLBACK_CONTEXT
    try:
        return await _plan(manager, social, message_id, user_msg, history)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Invalid JSON, timeout, missing provider or DB context must not reset memory.
        logger.warning(
            "VN social planning unavailable; keeping existing social state", exc_info=True
        )
        return FALLBACK_CONTEXT


async def _plan(
    manager: Any, social: SocialState, message_id: str, user_msg: str, history: list[dict]
) -> str:
    npcs = await _present_npcs(manager, social, user_msg)
    if not npcs:
        return FALLBACK_CONTEXT
    for npc in npcs:
        ensure_character(social, npc)
    source_id, scene_context = await _scene_evidence(manager)
    llm = GameMasterLLM.for_role(manager.user, "small")
    result = await asyncio.wait_for(
        llm.aexecute_complex_task(
            SYSTEM_PROMPT,
            _payload(
                social,
                npcs,
                user_msg,
                scene_context,
                history,
                recall_block(manager, "vn_social", {str(npc.id) for npc in npcs}),
            ),
            InteractionPlan,
            llm.model,
            game_id=manager.state.session_id,
            operation="vn_social",
            phase="reaction_plan",
            metadata={"message_id": message_id},
        ),
        timeout=PLANNING_TIMEOUT,
    )
    plan = InteractionPlan.model_validate(result)
    mark_processed(social, message_id)
    directed = apply_plan(social, plan, npcs, user_msg, scene_context, source_id)
    save_state(manager.state, social)
    return narrator_context(directed, npcs)
