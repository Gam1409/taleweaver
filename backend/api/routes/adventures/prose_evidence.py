"""An explicit, owner-only Debug inspection of the latest published exchange."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.editing.generation_errors import generation_error
from backend.core.auth import get_current_user
from backend.core.config import settings
from backend.core.database import get_db
from backend.core.llm_router import GameMasterLLM
from backend.engine import prose_evidence
from backend.engine.prose_evidence_catalog import Catalog, catalog
from backend.engine.turn_replay.control import story_message_filter
from backend.engine.turn_replay.snapshot import after
from backend.engine.visual_novel.concurrency import (
    BUSY_DETAIL,
    SessionBusyError,
    session_write_lease,
)
from backend.engine.visual_novel.continuity import PLAYER
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.models.user import User

router = APIRouter(tags=["Gameplay"])


async def _latest_exchange(db: AsyncSession, game_id: str) -> list[ChatMessage]:
    messages = list(
        reversed(
            (
                await db.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == game_id, story_message_filter())
                    .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                    .limit(2)
                )
            ).all()
        )
    )
    if [m.role for m in messages] != ["user", "assistant"] or any(m.is_debug for m in messages):
        raise HTTPException(409, "A published player and narrator exchange is required.")
    action = messages[0].content.lstrip().lower()
    if action.startswith("/") and not action.startswith("/say "):
        raise HTTPException(409, "Gameplay commands cannot be reviewed as story evidence.")
    if any(len(m.content) > prose_evidence.MAX_SOURCE for m in messages):
        raise HTTPException(422, "One of the messages exceeds the 12,000-character review limit.")
    return messages


async def _catalog_for_exchange(
    db: AsyncSession, state: SessionState, user: User, messages: list[ChatMessage]
) -> Catalog | None:
    game_id = state.session_id
    replay = await db.get(TurnReplay, game_id)
    if replay is not None and replay.status in {"pending", "executing", "replaying"}:
        raise HTTPException(409, "Finish or recover the current turn before reviewing evidence.")
    if (
        replay is None
        or replay.status != "ready"
        or replay.assistant_id != messages[1].id
        or replay.input_text != messages[0].content
        or not isinstance(replay.before, dict)
    ):
        return None
    # Equal player text can occur on several turns. Verify its position relative
    # to the saved boundary before using that snapshot for identity resolution.
    try:
        since = after(replay.before["boundary"])
    except (KeyError, TypeError, ValueError):
        return None
    first_input = await db.scalar(
        select(ChatMessage.id)
        .where(
            ChatMessage.session_id == game_id,
            ChatMessage.role == "user",
            story_message_filter(),
            since,
        )
        .order_by(ChatMessage.created_at, ChatMessage.id)
        .limit(1)
    )
    if first_input != messages[0].id:
        return None
    return catalog(replay.before, user_id=user.id, session_id=game_id, avatar_id=state.avatar_id)


async def _reviews(
    user: User, game_id: str, sources: list[dict], candidates: Catalog
) -> list[dict]:
    try:
        llm = GameMasterLLM.for_role(user, "small")
        llm.enable_thinking = False
        llm.max_tokens = min(llm.max_tokens, 3000)
    except Exception as exc:
        raise generation_error(exc, subject="prose evidence") from exc

    reviews = []
    failures = []
    for source in sources:
        try:
            report = await prose_evidence.review(llm, game_id, source, *candidates)
        except Exception as exc:
            failure = generation_error(exc, subject="prose evidence")
            failures.append(failure)
            report = {
                "message_id": source["id"],
                "revision_id": source["revision_id"],
                "role": source["role"],
                "error": failure.detail,
                "events": [],
                "discarded": 0,
            }
        reviews.append(report)
    if len(failures) == len(sources):
        raise failures[0]
    return reviews


async def _capture(game_id: str, db: AsyncSession, user: User) -> tuple[list[dict], Catalog | None]:
    state = await db.scalar(
        select(SessionState)
        .join(GameSession, GameSession.id == SessionState.session_id)
        .where(GameSession.id == game_id, GameSession.user_id == user.id)
    )
    if state is None:
        raise HTTPException(404, "Session not found.")
    if not (state.is_debug_enabled or settings.TALEWEAVER_DEBUG_ENABLED):
        raise HTTPException(403, "Enable gameplay Debug to review turn evidence.")
    messages = await _latest_exchange(db, game_id)
    candidates = await _catalog_for_exchange(db, state, user, messages)
    sources = [
        {"id": m.id, "revision_id": m.revision_id, "role": m.role, "content": m.content}
        for m in messages
    ]
    await db.commit()
    return sources, candidates


@router.post("/{game_id}/prose-evidence")
async def inspect_prose(
    game_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Findings refer to the captured message revisions even if play continues during inference."""
    owned = await db.scalar(
        select(GameSession.id).where(GameSession.id == game_id, GameSession.user_id == user.id)
    )
    if owned is None:
        raise HTTPException(404, "Session not found.")
    try:
        with session_write_lease(game_id):
            sources, candidates = await _capture(game_id, db, user)
    except SessionBusyError:
        raise HTTPException(409, BUSY_DETAIL) from None
    reviews = await _reviews(user, game_id, sources, candidates or ({PLAYER: "Player"}, {}))
    return {"sources": reviews, "has_snapshot": candidates is not None}
