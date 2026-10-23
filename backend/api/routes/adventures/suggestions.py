"""Read and refresh ideas independently of the game-turn stream."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.logic import AdventureLogic
from backend.api.routes.adventures.turn_suggestions import SuggestionGenerationError
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.models.user import User

router = APIRouter(tags=["Gameplay"])
SUGGESTIONS_TIMEOUT_SECONDS = 90


@router.get("/{game_id}/suggestions")
async def get_prompt_suggestions(
    game_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, list[str]]:
    """Returns stored or freshly generated spoiler-safe prompt suggestions."""
    state = await AdventureLogic.resolve_session_state(db, game_id, user_id=current_user.id)
    if not state:
        raise HTTPException(status_code=404, detail="Session state not found.")
    owner_id = state.session.user_id if state.session else state.user_id
    if owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session state not found.")

    manager = GameTurnManager(db, state.session_id, current_user)
    if not await manager.initialize():
        raise HTTPException(status_code=404, detail="Failed to initialize session.")

    suggestions = manager.suggestions.extract_prompt_suggestions(manager.state.exit_states or {})
    if not suggestions:
        last_response = await manager.suggestions.load_last_assistant_message()
        suggestions = await manager.suggestions.generate_prompt_suggestions(last_response)
        await db.commit()

    return {"suggestions": suggestions}


async def _context_version(manager: GameTurnManager) -> tuple[Any, ...]:
    """Detect a move or language change made while the model was answering."""
    return (
        manager.state.current_scene_id,
        manager.state.in_game_time,
        manager.suggestions.content_language(),
        await manager.suggestions.load_last_assistant_message(),
    )


@router.post("/{game_id}/suggestions")
@router.post("/{game_id}/shuffle")
async def shuffle_prompt_suggestions(
    game_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, list[str]]:
    """Refresh ideas without adding chat messages, advancing time, or hiding failures."""
    state = await AdventureLogic.resolve_session_state(db, game_id, user_id=current_user.id)
    if not state:
        raise HTTPException(status_code=404, detail="Session state not found.")
    owner_id = state.session.user_id if state.session else state.user_id
    if owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session state not found.")
    manager = GameTurnManager(db, state.session_id, current_user)
    if not await manager.initialize():
        raise HTTPException(status_code=404, detail="Failed to initialize session.")

    version = await _context_version(manager)
    try:
        suggestions = await asyncio.wait_for(
            manager.suggestions.generate_prompt_suggestions(version[-1], refresh=True),
            timeout=SUGGESTIONS_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Idea generation timed out.") from exc
    except SuggestionGenerationError as exc:
        raise HTTPException(
            status_code=502, detail="The Small / Utility model could not generate valid ideas."
        ) from exc

    # Merge only the ideas into current state; never overwrite concurrent exit updates.
    await db.refresh(manager.state)
    if manager.state.session is not None:
        await db.refresh(manager.state.session)
    if await _context_version(manager) != version:
        raise HTTPException(status_code=409, detail="The scene changed. Refresh ideas again.")
    manager.suggestions.set_prompt_suggestions_state(suggestions)
    await db.commit()
    return {"suggestions": suggestions}
