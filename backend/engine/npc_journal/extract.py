"""Prepare a small, spoiler-aware extraction request after narration is complete."""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.content_language import prose_language_instruction
from backend.core.llm_router import GameMasterLLM
from backend.engine.npc_journal.records import journal_of, memory_context
from backend.engine.npc_journal.schema import SYSTEM_PROMPT, JournalExtraction
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.models.world_entity import WorldEntity


async def extraction_context(
    db: AsyncSession, message: ChatMessage, session: GameSession
) -> tuple[str, str]:
    avatar = await db.get(Avatar, session.avatar_id)
    player_name = avatar.name if avatar else ""
    npcs = list(
        (
            await db.scalars(
                select(WorldEntity).where(
                    WorldEntity.session_id == session.id,
                    WorldEntity.entity_type == "NPC",
                    WorldEntity.is_hidden.is_(False),
                )
            )
        ).all()
    )
    known = [
        {
            "npc_id": npc.id,
            "name": npc.name,
            "scene_id": npc.current_scene_id,
            "aliases": journal_of(npc).get("aliases", []),
            "appearance": npc.description,
            "learned": memory_context(npc, 800),
        }
        for npc in npcs
    ]
    previous = await db.scalar(
        select(ChatMessage.content)
        .where(
            ChatMessage.session_id == session.id,
            ChatMessage.role == "user",
            ChatMessage.created_at <= message.created_at,
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    payload = {
        "player_name": player_name,
        "scene_id": message.scene_id,
        "known_characters": known,
        "player_message_for_context_only": (previous or "")[:3000],
        "current_narration": message.content[:24000],
    }
    return json.dumps(payload, ensure_ascii=False), player_name


async def extract(
    user: User, session: GameSession, message_id: str, payload: str
) -> JournalExtraction:
    llm = GameMasterLLM.for_role(user, "small")
    return await llm.aexecute_complex_task(
        SYSTEM_PROMPT
        + prose_language_instruction(
            session.content_language or user.default_language or "English", "observation text"
        ),
        payload,
        JournalExtraction,
        llm.model,
        adventure_id=session.template_id,
        game_id=session.id,
        operation="npc_journal",
        phase="observations",
        metadata={"message_id": message_id},
    )
