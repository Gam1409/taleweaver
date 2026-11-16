"""Session-only opt-ins, serialized with turns and preserved during turn replay."""

import logging
from copy import deepcopy
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Text, cast, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.npc_presentation import PortraitPreferences, PreferencesUpdate
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay

KEY = "__npc_portrait_preferences__"
logger = logging.getLogger(__name__)


class PreferencesConflictError(ValueError):
    """No settings are overwritten when a session or preview has changed."""


def read(states: dict[str, Any] | None) -> PortraitPreferences:
    raw = states.get(KEY) if isinstance(states, dict) else None
    try:
        return PortraitPreferences.model_validate({} if raw is None else raw)
    except ValidationError as exc:
        raise PreferencesConflictError("Stored portrait settings are invalid.") from exc


def effective(state: Any) -> PortraitPreferences:
    try:
        return read(getattr(state, "entity_states", None))
    except PreferencesConflictError:
        logger.warning("Invalid portrait preferences; optional presentation is disabled.")
        return PortraitPreferences()


def replace(states: dict | None, preferences: PortraitPreferences) -> dict:
    result = deepcopy(states or {})
    result[KEY] = preferences.model_dump()
    return result


async def save(
    db: AsyncSession, state: SessionState, before: str | None, payload: PreferencesUpdate
) -> PortraitPreferences:
    current = read(state.entity_states)
    if current != payload.expected:
        raise PreferencesConflictError("Portrait settings changed elsewhere. Reload before saving.")
    if current == payload.settings:
        return current
    replay = await db.scalar(select(TurnReplay).where(TurnReplay.session_id == state.session_id))
    replay_before = _updated_replay(replay, payload.settings)
    changed = await db.execute(
        update(SessionState)
        .where(SessionState.id == state.id, cast(SessionState.entity_states, Text) == before)
        .values(entity_states=replace(state.entity_states, payload.settings))
        .returning(SessionState.id)
        .execution_options(synchronize_session=False)
    )
    if changed.scalar_one_or_none() is None:
        raise PreferencesConflictError("Session state changed. Reload the settings and try again.")
    if replay is not None and replay_before is not None:
        replay.before = replay_before
    await db.commit()
    return payload.settings


def _updated_replay(replay: TurnReplay | None, preferences: PortraitPreferences) -> dict | None:
    if replay is None:
        return None
    if replay.status == "replaying":
        raise PreferencesConflictError("A turn is being recovered. Reopen the session first.")
    result = deepcopy(replay.before)
    state = result.get("state") if isinstance(result, dict) else None
    if not isinstance(state, dict) or not isinstance(state.get("entity_states"), dict):
        raise PreferencesConflictError(
            "The saved turn snapshot is unavailable. Play a new turn first."
        )
    state["entity_states"] = replace(state["entity_states"], preferences)
    return result
