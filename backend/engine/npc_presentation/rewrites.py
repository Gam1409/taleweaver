"""Reuse the single rewrite request for optional portrait metadata."""

from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.npc_presentation.runtime import PresentationTurn, prepare
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity


async def prepare_rewrite(db: AsyncSession, session_id: str) -> PresentationTurn:
    state = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
    entities = list(
        await db.scalars(select(WorldEntity).where(WorldEntity.session_id == session_id))
    )
    return prepare(SimpleNamespace(state=state), entities)


def clean_rewrite(turn: PresentationTurn, text: str) -> str:
    result = turn.clean(text).strip()
    if not result:
        raise ValueError("Regeneration returned no narration")
    return result
