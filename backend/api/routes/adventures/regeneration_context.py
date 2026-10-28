"""Read-only narration guidance for rewriting an already committed response."""

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import prompts
from backend.engine.memory_manager import MemoryManager
from backend.engine.npc_presence import presence_context
from backend.engine.visual_novel.narration import narration_suffix
from backend.engine.visual_novel.presentation import session_is_vn
from backend.models.adventure_template import AdventureTemplate
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


async def narration_guidance(db: AsyncSession, session: GameSession, user: User) -> str:
    state = await db.scalar(select(SessionState).where(SessionState.session_id == session.id))
    if state is None:
        raise HTTPException(409, "Session state is unavailable. Reload the session.")
    adventure = await db.get(AdventureTemplate, state.template_id) if state.template_id else None
    snapshot = (state.entity_states or {}).get("__manifest_snapshot__") or {}
    saved = snapshot.get("adventure") or {}
    mode = "vn" if await session_is_vn(db, state) else "chat"
    frame = MemoryManager.build_static_prompt(
        getattr(adventure, "original_prompt", None) or saved.get("original_prompt", ""),
        plot=_text(state.plot or getattr(adventure, "plot", None) or saved.get("plot")),
        rules=_text(state.rules or getattr(adventure, "rules", None) or saved.get("rules")),
        walkthrough=state.walkthrough or getattr(adventure, "walkthrough", None),
        rule_enforcement_mode=mode,
    )
    suffix = narration_suffix(state) if mode == "vn" else prompts.GM_NARRATION_MANDATORY_FORMATTING
    tts = user.tts_settings or {}
    voice = (
        prompts.get_vocal_direction_prompt(tts.get("provider", "google"))
        if tts.get("use_vocal_tags", True)
        else ""
    )
    entities = list(
        await db.scalars(select(WorldEntity).where(WorldEntity.session_id == session.id))
    )
    facts = {
        "scene_id": state.current_scene_id,
        "in_game_time": state.in_game_time,
        "source_of_truth": "The original response and committed state; do not replay the action.",
    }
    return "\n\n".join((frame, suffix, voice, presence_context(entities, state), json.dumps(facts)))
