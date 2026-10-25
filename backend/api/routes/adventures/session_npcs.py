"""Owned session character cards, learned history, and explicit retry of failed learning."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.npc_journal.portraits import portrait_status
from backend.engine.npc_journal.records import journal_of
from backend.engine.npc_journal.relationships import player_relationship
from backend.engine.npc_journal.worker import schedule
from backend.engine.visual_novel.state import public_profile
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity

router = APIRouter(tags=["Session characters"])


async def _state(db: AsyncSession, game_id: str, user: User) -> SessionState:
    state = await db.scalar(
        select(SessionState)
        .join(GameSession)
        .where(
            GameSession.id == game_id,
            GameSession.user_id == user.id,
        )
    )
    if state is None:
        raise HTTPException(404, "Session not found.")
    return state


def _known(npc: WorldEntity, state: SessionState) -> bool:
    override = (state.entity_states or {}).get(npc.id) or {}
    journal = journal_of(npc)
    if journal.get("introduction") or journal.get("entries"):
        return True
    return (
        not override.get("is_hidden", npc.is_hidden)
        and override.get("current_scene_id", npc.current_scene_id) == state.current_scene_id
    )


def _card(npc: WorldEntity, state: SessionState) -> dict:
    journal = journal_of(npc)
    override = (state.entity_states or {}).get(npc.id) or {}
    return {
        "id": npc.id,
        "name": override.get("name", npc.name),
        "description": override.get("description", npc.description),
        "image_url": override.get("image_url", npc.image_url),
        "scene_id": state.current_scene_id
        if override.get("current_scene_id", npc.current_scene_id) == state.current_scene_id
        and not override.get("is_hidden", npc.is_hidden)
        else None,
        "aliases": journal.get("aliases", []),
        "introduction": journal.get("introduction"),
        "relationship": player_relationship(journal),
        "portrait_status": "ready"
        if npc.image_url
        else portrait_status(state.session_id, npc.id, journal.get("portrait_status")),
        "entry_count": len(journal.get("entries") or []),
        "narrative_role": "major"
        if public_profile(state, npc.id)["importance"] == "hero"
        else "supporting",
    }


@router.get("/{game_id}/npcs")
async def list_characters(
    game_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    state = await _state(db, game_id, user)
    schedule(game_id, user.id)
    npcs = (
        await db.scalars(
            select(WorldEntity)
            .where(
                WorldEntity.session_id == game_id,
                WorldEntity.entity_type == "NPC",
            )
            .order_by(WorldEntity.name)
        )
    ).all()
    tasks = (
        await db.scalars(
            select(ChatMessage.npc_journal).where(
                ChatMessage.session_id == game_id,
                ChatMessage.npc_journal.is_not(None),
            )
        )
    ).all()
    statuses = [task.get("status") for task in tasks if isinstance(task, dict)]
    return {
        "characters": [_card(npc, state) for npc in npcs if _known(npc, state)],
        "pending": sum(s in ("pending", "running") for s in statuses),
        "failed": statuses.count("failed"),
    }


@router.get("/{game_id}/npcs/{npc_id}")
async def character_details(
    game_id: str,
    npc_id: str,
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    state = await _state(db, game_id, user)
    npc = await db.scalar(
        select(WorldEntity).where(
            WorldEntity.session_id == game_id,
            WorldEntity.id == npc_id,
            WorldEntity.entity_type == "NPC",
        )
    )
    if npc is None or not _known(npc, state):
        raise HTTPException(404, "Character not found.")
    entries = list(reversed(journal_of(npc).get("entries") or []))
    return {
        **_card(npc, state),
        "entries": entries[offset : offset + 50],
        "has_more": len(entries) > offset + 50,
    }


@router.post("/{game_id}/npc-journal/retry")
async def retry_learning(
    game_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    await _state(db, game_id, user)
    messages = (
        await db.scalars(
            select(ChatMessage).where(
                ChatMessage.session_id == game_id,
                ChatMessage.npc_journal["status"].as_string() == "failed",
            )
        )
    ).all()
    for message in messages:
        message.npc_journal = {"status": "pending", "attempts": 0}
    await db.commit()
    schedule(game_id, user.id)
    return {"queued": len(messages)}
