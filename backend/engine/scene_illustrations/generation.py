"""Generate asynchronously and attach only to an unchanged saved VN message."""

import asyncio
from copy import deepcopy
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import database
from backend.core.visual_queries import collect_queries
from backend.core.visual_trace import current_id, record, traced
from backend.engine.image_profiles import image_timeout
from backend.engine.media_engine import MediaEngine
from backend.engine.memory_rag.persistence import retry_transaction
from backend.models.session_state import SessionState
from backend.models.user import User

from .context import owned_context, require_snapshot
from .render import image_request, prepare_moment_prompt
from .snapshots import MAX_NARRATION, REGISTRY_KEY, registry_of


class SceneIllustrationRequest(BaseModel):
    message_id: str = Field(min_length=1, max_length=128)


async def _try_attach(
    db: AsyncSession,
    session_id: str,
    message_id: str,
    owner_id: str,
    snapshot: dict,
    url: str,
    details: dict | None = None,
) -> bool:
    state, message = await owned_context(db, session_id, message_id, owner_id)
    current = require_snapshot(state, message)
    if current.get("nonce") != snapshot.get("nonce"):
        raise HTTPException(409, "The story changed while generating. This image was not attached.")
    before = deepcopy(state.entity_states or {})
    after = deepcopy(before)
    registry = registry_of(after)
    registry["images"][message_id] = {
        "image_url": url,
        "content_hash": current["content_hash"],
        "generation_details": deepcopy(details) if details else None,
    }
    after[REGISTRY_KEY] = registry
    # Compare-and-swap keeps unrelated concurrent state changes intact.
    result = await db.execute(
        update(SessionState)
        .where(SessionState.id == state.id, SessionState.entity_states == before)
        .values(entity_states=after)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        return False
    await db.commit()
    return True


@retry_transaction
async def _attach_once(
    session_id: str,
    message_id: str,
    owner_id: str,
    snapshot: dict,
    url: str,
    details: dict | None = None,
) -> bool:
    async with database.AsyncSessionLocal() as db:
        return await _try_attach(db, session_id, message_id, owner_id, snapshot, url, details)


async def _attach(
    session_id: str,
    message_id: str,
    owner_id: str,
    snapshot: dict,
    url: str,
    details: dict | None = None,
) -> None:
    for _attempt in range(3):
        if await _attach_once(session_id, message_id, owner_id, snapshot, url, details):
            return
    raise HTTPException(409, "The session changed while attaching the illustration. Try again.")


@traced
async def generate_scene_illustration(
    session_id: str, payload: SceneIllustrationRequest, db: AsyncSession, user: User
) -> dict:
    state, message = await owned_context(db, session_id, payload.message_id, user.id)
    snapshot = {
        **require_snapshot(state, message),
        "narration": message.content[-MAX_NARRATION:],
        "full_narration": message.content,
    }
    # The hash-verified message also repairs old snapshots that retained the beginning.
    record("snapshot", narration=snapshot["narration"], visible_facts=snapshot["visible_facts"])
    request = None
    owner_id = user.id
    try:
        request, t2i = await image_request(db, state, user, snapshot)
        # The provider queue must not hold a database transaction open.
        await db.commit()
        details: dict = {"trace_id": current_id()} if current_id() else {}
        details["context_mode"] = (
            "neutral_source" if request["provider_options"].get("_neutral_source") else "bounded"
        )
        request["provider_options"]["_generation_details"] = details
        with collect_queries() as queries:
            await prepare_moment_prompt(request)
            url = await asyncio.wait_for(
                MediaEngine.generate_image(**request), timeout=image_timeout(t2i)
            )
        details["queries"] = queries
        if not url:
            raise HTTPException(502, "No illustration was returned. Any previous image was kept.")
        await _attach(session_id, payload.message_id, owner_id, snapshot, url, details)
    except TimeoutError as exc:
        raise HTTPException(
            504, "Illustration generation timed out. A remote task may still be running."
        ) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except HTTPException:
        if request:
            # The unique path was created by this request, never supplied by a client.
            Path(request["target_dir"], request["filename"]).unlink(missing_ok=True)
        raise
    return {
        "status": "success",
        "message_id": payload.message_id,
        "image_url": url,
        "generation_details": details or None,
    }
