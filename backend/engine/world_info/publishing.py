"""Explicit selected-entry publication shares the scalable batch contract."""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.world_info.access import WorldInfoError, owned_entry, reserve_session_write
from backend.engine.world_info.publication_batch import publish_selection
from backend.engine.world_info.schemas import Publish
from backend.models.world_info import WorldInfoSource


async def publish(
    db: AsyncSession, user_id: str, session_id: str, payload: Publish
) -> tuple[int, int, WorldInfoSource]:
    await reserve_session_write(db, user_id, session_id)
    entries = [await owned_entry(db, user_id, session_id, item.id) for item in payload.entries]
    if any(
        entry.version != item.version for entry, item in zip(entries, payload.entries, strict=True)
    ):
        raise WorldInfoError(
            "Selected entries changed. Review the publication selection again.", 409
        )
    return await publish_selection(
        db,
        user_id,
        session_id,
        payload.revision_id,
        entries,
        expected_source_version=payload.source_version,
    )
