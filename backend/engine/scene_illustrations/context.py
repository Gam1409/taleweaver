"""Ownership and message-version checks for manual VN illustrations."""

from typing import cast

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.visual_novel.presentation import session_is_vn
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.utils.path_security import sanitize_path_component

from .snapshots import content_hash, registry_of


async def owned_context(
    db: AsyncSession, session_id: str, message_id: str, owner_id: str
) -> tuple[SessionState, ChatMessage]:
    if sanitize_path_component(session_id) != session_id:
        raise HTTPException(404, "Session not found.")
    state = await db.scalar(
        select(SessionState)
        .join(GameSession, GameSession.id == SessionState.session_id)
        .where(GameSession.id == session_id, GameSession.user_id == owner_id)
        .execution_options(populate_existing=True)
    )
    if state is None:
        raise HTTPException(404, "Session not found.")
    if not await session_is_vn(db, state):
        raise HTTPException(400, "Turn illustrations are available in Visual Novel sessions only.")
    message = await db.scalar(
        select(ChatMessage)
        .where(ChatMessage.id == message_id, ChatMessage.session_id == session_id)
        .execution_options(populate_existing=True)
    )
    if message is None:
        raise HTTPException(404, "Message not found in this session.")
    if message.role != "assistant":
        raise HTTPException(400, "Choose a completed narrator message to illustrate.")
    return state, message


def illustration_status(state: SessionState, message: ChatMessage) -> dict:
    registry = registry_of(state.entity_states)
    snapshot = registry["snapshots"].get(message.id) or {}
    image = getattr(message, "illustration", None) or registry["images"].get(message.id) or {}
    digest = content_hash(message)
    available = snapshot.get("content_hash") == digest
    return {
        "message_id": message.id,
        "plan_enabled": True,
        "staging_status": (snapshot.get("visible_facts") or {}).get("staging_status"),
        "available": available,
        "reason": None
        if available
        else "No matching visual snapshot remains for this message. New narrator turns keep the latest 100 snapshots.",
        "image_url": image.get("image_url") if image.get("content_hash") == digest else None,
        "generation_details": image.get("generation_details")
        if image.get("content_hash") == digest
        else None,
        "snapshot_source": "message_time" if available else None,
    }


def require_snapshot(state: SessionState, message: ChatMessage) -> dict:
    status = illustration_status(state, message)
    if not status["available"]:
        raise HTTPException(409, status["reason"])
    return cast(dict, registry_of(state.entity_states)["snapshots"][message.id])


async def plan_enabled(db: AsyncSession, state: SessionState) -> bool:
    """Match the story policy used by image settings without requiring a provider."""
    from backend.engine.nsfw.settings import nsfw_settings
    from backend.models.adventure_template import AdventureTemplate

    snapshot = (state.entity_states or {}).get("__manifest_snapshot__")
    if isinstance(snapshot, dict) and snapshot:
        return not nsfw_settings(snapshot.get("original_manifest"))["enabled"]
    template = await db.get(AdventureTemplate, state.template_id) if state.template_id else None
    return not nsfw_settings(getattr(template, "original_manifest", None))["enabled"]
