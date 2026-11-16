"""Owner-scoped narrator preferences and editable open-ended world briefs."""

from typing import Any
from typing import cast as type_cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Text, cast, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.core.narrator_voices import default_narrator_voices
from backend.engine.blueprint.brief import BRIEF_KEY, SOURCES_KEY, WorldBrief
from backend.engine.narrator.settings import (
    MANIFEST_KEY,
    SETTINGS_KEY,
    NarratorSettings,
    manifest_settings,
    preserve_missing_flow,
    read_settings,
)
from backend.engine.visual_novel.concurrency import (
    BUSY_DETAIL,
    SessionBusyError,
    session_write_lease,
)
from backend.models.adventure_template import AdventureTemplate
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User

router = APIRouter(tags=["Narrator presentation"])


def _response(settings: NarratorSettings) -> dict[str, Any]:
    return {"settings": settings.model_dump(), "voices": default_narrator_voices()}


async def _template(db: AsyncSession, template_id: str, user: User) -> Any:
    row = (
        await db.execute(
            select(
                AdventureTemplate,
                cast(AdventureTemplate.original_manifest, Text).label("manifest_json"),
            )
            .where(AdventureTemplate.id == template_id, AdventureTemplate.owner_id == user.id)
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Adventure template not found.")
    return row


async def _state(db: AsyncSession, game_id: str, user: User) -> Any:
    row = (
        await db.execute(
            select(SessionState, cast(SessionState.entity_states, Text).label("state_json"))
            .join(GameSession, GameSession.id == SessionState.session_id)
            .where(GameSession.id == game_id, GameSession.user_id == user.id)
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Session not found.")
    return row


async def _commit(db: AsyncSession, statement: Any) -> None:
    result = await db.execute(statement.execution_options(synchronize_session=False))
    if type_cast(CursorResult[Any], result).rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "Settings changed during saving. Reload and try again.")
    await db.commit()


@router.get("/{template_id}/narrator-defaults", response_model=None)
async def read_defaults(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    adventure, _ = await _template(db, template_id, user)
    return _response(manifest_settings(adventure.original_manifest))


@router.put("/{template_id}/narrator-defaults", response_model=None)
async def save_defaults(
    template_id: str,
    payload: NarratorSettings,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    adventure, before = await _template(db, template_id, user)
    _ensure_editable(adventure)
    manifest = adventure.original_manifest if isinstance(adventure.original_manifest, dict) else {}
    payload = preserve_missing_flow(payload, manifest_settings(manifest))
    await _commit(
        db,
        update(AdventureTemplate)
        .where(
            AdventureTemplate.id == adventure.id,
            cast(AdventureTemplate.original_manifest, Text) == before,
        )
        .values(original_manifest={**manifest, MANIFEST_KEY: payload.model_dump()}),
    )
    return _response(payload)


@router.get("/{game_id}/narrator-settings", response_model=None)
async def read_session(
    game_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    state, _ = await _state(db, game_id, user)
    return _response(read_settings(state))


@router.put("/{game_id}/narrator-settings", response_model=None)
async def save_session(
    game_id: str,
    payload: NarratorSettings,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    owned_id = await db.scalar(
        select(GameSession.id).where(GameSession.id == game_id, GameSession.user_id == user.id)
    )
    if owned_id is None:
        raise HTTPException(404, "Session not found.")
    try:
        with session_write_lease(game_id):
            state, before = await _state(db, game_id, user)
            states = state.entity_states if isinstance(state.entity_states, dict) else {}
            payload = preserve_missing_flow(payload, read_settings(state))
            await _commit(
                db,
                update(SessionState)
                .where(
                    SessionState.id == state.id, cast(SessionState.entity_states, Text) == before
                )
                .values(entity_states={**states, SETTINGS_KEY: payload.model_dump()}),
            )
    except SessionBusyError:
        raise HTTPException(409, BUSY_DETAIL) from None
    return _response(payload)


def _ensure_editable(adventure: AdventureTemplate) -> None:
    if (
        adventure.generation_run_id
        and not adventure.is_ready
        and adventure.creation_status not in {"Failed", "Cancelled", None}
    ):
        raise HTTPException(
            409, "Wait for adventure generation to finish before changing author settings."
        )


@router.get("/{template_id}/world-brief", response_model=WorldBrief)
async def read_world_brief(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorldBrief:
    adventure, _ = await _template(db, template_id, user)
    return WorldBrief.model_validate((adventure.original_manifest or {}).get(BRIEF_KEY) or {})


@router.put("/{template_id}/world-brief", response_model=WorldBrief)
async def save_world_brief(
    template_id: str,
    payload: WorldBrief,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorldBrief:
    adventure, before = await _template(db, template_id, user)
    _ensure_editable(adventure)
    manifest = dict(adventure.original_manifest or {})
    previous = WorldBrief.model_validate(manifest.get(BRIEF_KEY) or {})
    if previous.references != payload.references:
        manifest.pop(SOURCES_KEY, None)
    manifest[BRIEF_KEY] = payload.model_dump()
    await _commit(
        db,
        update(AdventureTemplate)
        .where(
            AdventureTemplate.id == adventure.id,
            cast(AdventureTemplate.original_manifest, Text) == before,
        )
        .values(original_manifest=manifest),
    )
    return payload
