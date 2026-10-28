"""Prepare a small, spoiler-aware extraction request after narration is complete."""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.content_language import prose_language_instruction
from backend.core.llm_router import GameMasterLLM
from backend.engine.npc_journal.records import is_significant, journal_of
from backend.engine.npc_journal.schema import SYSTEM_PROMPT, JournalExtraction
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.models.world_entity import WorldEntity

MAX_KNOWN_CHARACTERS_CHARS = 12000


def _known_facts(npc: WorldEntity) -> list[dict]:
    """Expose bounded distinct prior facts, including older legacy general topics."""
    facts = []
    remaining = 1600
    for entry in reversed((journal_of(npc).get("entries") or [])[-32:]):
        text = str(entry.get("text") or "")[:400]
        if len(text) > remaining:
            continue
        facts.append(
            {
                "topic": entry.get("topic", "general"),
                "text": text,
                "source": entry.get("source", "observed"),
            }
        )
        remaining -= len(text)
    return list(reversed(facts))


def _bounded_known(npcs: list[WorldEntity], message: ChatMessage) -> list[dict]:
    """Prioritize this scene; a growing cast must not grow the extraction prompt forever."""
    narration = message.content.casefold()

    def relevant(npc: WorldEntity) -> bool:
        return npc.current_scene_id == message.scene_id or bool(
            npc.name and npc.name.casefold() in narration
        )

    known = []
    remaining = MAX_KNOWN_CHARACTERS_CHARS - 2
    for npc in sorted(npcs, key=lambda npc: (not relevant(npc), str(npc.id))):
        row = {"npc_id": npc.id, "name": npc.name, "scene_id": npc.current_scene_id}
        if relevant(npc):
            row.update(
                aliases=journal_of(npc).get("aliases", [])[:5],
                appearance=(npc.description or "")[:1000],
                learned=_known_facts(npc),
            )
        size = len(json.dumps(row, ensure_ascii=False)) + 2
        if size > remaining:
            row = {"npc_id": npc.id, "name": npc.name}
            size = len(json.dumps(row, ensure_ascii=False)) + 2
        if size <= remaining:
            known.append(row)
            remaining -= size
    return known


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
    known = _bounded_known(npcs, message)
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
    result = await llm.aexecute_complex_task(
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
    extraction = JournalExtraction.model_validate(result)
    # Optional fields permit old stored/imported payloads, not unclassified new output.
    # Retain valid identity introductions even when every proposed observation is rejected.
    for character in extraction.characters:
        character.observations = [
            observation
            for observation in character.observations
            if observation.significance is not None and is_significant(observation)
        ]
    return extraction
