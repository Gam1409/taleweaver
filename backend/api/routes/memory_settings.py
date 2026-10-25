"""Embedding preferences are independent from completion provider settings."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_admin
from backend.core.database import get_db
from backend.core.security import encryption_util
from backend.engine.memory_rag.control import ensure_index_states, invalidate
from backend.engine.memory_rag.embeddings import EmbeddingError, embed_with_settings
from backend.engine.memory_rag.settings import MemoryRagSettings, read_settings
from backend.models.user import User

router = APIRouter(prefix="/settings/memory-rag", tags=["Memory"])
logger = logging.getLogger(__name__)


class MemorySettingsPayload(MemoryRagSettings):
    api_key: str | None = Field(default=None, max_length=4096, repr=False)
    clear_api_key: bool = False

    @model_validator(mode="after")
    def require_endpoint(self):
        if self.enabled and (not self.base_url or not self.model):
            raise ValueError("Enabled memory search requires an embedding URL and model.")
        return self

    def public_config(self) -> dict:
        return self.model_dump(exclude={"api_key", "clear_api_key"})


def public_settings(user: User) -> dict:
    return {
        **read_settings(user).model_dump(),
        "key_configured": bool((user.encrypted_api_keys or {}).get("memory_embeddings")),
    }


async def settings_owner(db: AsyncSession, user: User) -> User:
    from backend.api.routes.config_api import _resolve_global_settings_owner

    return await _resolve_global_settings_owner(db, user)


@router.get("")
async def get_memory_settings(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_admin)
) -> dict:
    return public_settings(await settings_owner(db, user))


@router.put("")
async def save_memory_settings(
    payload: MemorySettingsPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin),
) -> dict:
    from backend.api.routes.config_api import _broadcast_global_settings

    owner = await settings_owner(db, user)
    before = read_settings(owner).model_dump()
    after = payload.public_config()
    owner.llm_settings = {**(owner.llm_settings or {}), "memory_rag": after}
    keys = dict(owner.encrypted_api_keys or {})
    if payload.clear_api_key:
        keys.pop("memory_embeddings", None)
    if payload.api_key and payload.api_key.strip():
        keys["memory_embeddings"] = encryption_util.encrypt_key(payload.api_key.strip())
    owner.encrypted_api_keys = keys
    await _broadcast_global_settings(db, owner)
    rows = await ensure_index_states(db)
    if before != after or payload.api_key or payload.clear_api_key:
        for row in rows:
            invalidate(row)
    result = public_settings(owner)
    # Keep source IDs available with expire_on_commit sessions.
    scheduling = [(row.session_id, row.user_id, row.paused) for row in rows]
    await db.commit()
    if after["enabled"]:
        from backend.engine.memory_rag.worker import schedule

        for session_id, user_id, paused in scheduling:
            if not paused:
                schedule(session_id, user_id)
    return result


@router.post("/test")
async def test_memory_settings(
    payload: MemorySettingsPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin),
) -> dict:
    owner = await settings_owner(db, user)
    config = MemoryRagSettings.model_validate({**payload.public_config(), "enabled": True})
    if not config.base_url or not config.model:
        raise HTTPException(422, "An embedding URL and model are required.")
    key = payload.api_key or ""
    if not key and not payload.clear_api_key:
        encrypted = (owner.encrypted_api_keys or {}).get("memory_embeddings")
        if encrypted:
            key = encryption_util.decrypt_key(encrypted)
    try:
        vectors = await embed_with_settings(config, ["Memory connection test."], api_key=key)
    except EmbeddingError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.warning("Memory embedding test failed: %s", type(exc).__name__)
        raise HTTPException(
            400, "Embedding connection failed. Check the endpoint and model."
        ) from exc
    return {"ok": True, "message": "Embedding connection succeeded.", "dimensions": len(vectors[0])}
