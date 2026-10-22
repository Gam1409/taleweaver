"""Persist content language independently of game-state checkpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.content_language import default_language, normalize_language
from backend.core.database import get_db
from backend.models.game_session import GameSession
from backend.models.user import User

router = APIRouter(tags=["Gameplay"])


def resolve_content_language(
    state: Any, user: Any, adventure: Any, requested: str | None = None
) -> str:
    """A legacy per-request override takes priority over the saved session choice."""
    if requested:
        return normalize_language(requested) or "English"
    session = state.session if state is not None else None
    return default_language(
        getattr(session, "content_language", None),
        getattr(user, "default_language", None),
        getattr(adventure, "language", None),
    )


def initialize_content_language(state: Any, user: Any, adventure: Any) -> str:
    """Freeze the initial default on first access, including for older sessions."""
    language = resolve_content_language(state, user, adventure)
    if state.session is not None and state.session.content_language != language:
        state.session.content_language = language
    return language


class ContentLanguageUpdate(BaseModel):
    language: str

    @field_validator("language")
    @classmethod
    def valid_language(cls, value: str) -> str:
        return normalize_language(value) or ""


@router.patch("/{game_id}/content-language")
async def update_content_language(
    game_id: str,
    payload: ContentLanguageUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Save a session choice and replace suggestions written in the previous language."""
    from backend.api.routes.adventures.gameplay_logic import GameTurnManager

    session = await db.get(GameSession, game_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found.")
    manager = GameTurnManager(db, game_id, current_user)
    if not await manager.initialize() or manager.state.session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    language = payload.language or default_language(
        current_user.default_language, manager.adventure.language
    )
    manager.state.session.content_language = language
    manager.turn_language = language
    context = await manager.suggestions.build_player_only_suggestion_context()
    suggestions = manager.suggestions.fallback_prompt_suggestions(
        scene_label=context["scene_label"],
        visible_objects=context["visible_objects"],
        visible_npcs=context["visible_npcs"],
        inventory_items=context["inventory_items"],
    )
    manager.suggestions.set_prompt_suggestions_state(suggestions)
    await db.commit()
    return {"language": language, "prompt_suggestions": suggestions}
