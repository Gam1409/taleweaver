"""REST endpoints driving the autonomous play-agent from the in-game control panel."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.agent_turn_stream import ensure_agent_active, stream_agent_turn
from backend.api.routes.adventures.session_mutations import session_mutation_lease
from backend.api.routes.adventures.stream_transport import heartbeat_stream
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.gameplay.agent_settings import (
    AgentSettingsUpdate,
    apply_settings_update,
    build_agent_snapshot,
)
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.visual_novel.concurrency import SessionLease
from backend.models.user import User

router = APIRouter(tags=["Play-Agent"], dependencies=[Depends(session_mutation_lease)])


@router.post("/{game_id}/agent/turn", response_model=None)
async def run_agent_turn(
    game_id: str,
    lease: SessionLease = Depends(session_mutation_lease),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Computes an agent decision based on walkthrough & game state, then executes the turn."""
    await ensure_agent_active(game_id, current_user)
    return StreamingResponse(
        heartbeat_stream(stream_agent_turn(game_id, current_user, lease=lease)),
        media_type="text/event-stream",
        headers={"X-Taleweaver-Turn-Id": uuid4().hex},
    )


@router.patch("/{game_id}/agent/settings", response_model=None)
async def update_agent_settings(
    game_id: str,
    payload: AgentSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Updates play-agent mode, personality and options for a session."""
    manager = GameTurnManager(db, game_id, current_user)
    if not await manager.initialize() or manager.state is None:
        raise HTTPException(status_code=404, detail="Game session not found.")
    try:
        apply_settings_update(manager.state, payload, current_user.llm_settings)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unknown play-agent personality.") from None
    await db.commit()
    return build_agent_snapshot(manager.state)
