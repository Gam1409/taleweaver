"""Shared global-settings lookup and game-settings defaults."""

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.user import User


async def resolve_global_settings_owner(
    db: AsyncSession, fallback_user: User, *, for_update: bool = False
) -> User:
    """Return the global settings owner, optionally locking JSON merges against stale reads."""
    admin_res = await db.execute(select(User).where(User.role == "admin").limit(1))
    owner = admin_res.scalars().first() or fallback_user
    if for_update:
        # SQLite has no SELECT FOR UPDATE. Own the write lock before re-reading the
        # shared JSON columns; the caller commits immediately after its settings save.
        await db.execute(update(User).where(User.id == owner.id).values(id=owner.id))
        await db.refresh(owner, attribute_names=["llm_settings", "encrypted_api_keys"])
    return owner


def normalize_game_settings(game_settings: Optional[dict]) -> dict:
    fallback = {
        "clock_24h": False,
        "date_format": "DD.MM.YY",
        "whisper_model": "tiny",
    }
    if not game_settings:
        return fallback
    normalized = dict(game_settings)
    if "clock_24h" not in normalized:
        normalized["clock_24h"] = False
    if "date_format" not in normalized:
        normalized["date_format"] = "DD.MM.YY"
    if "whisper_model" not in normalized:
        normalized["whisper_model"] = "tiny"
    return normalized
