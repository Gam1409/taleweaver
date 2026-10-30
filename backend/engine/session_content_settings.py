"""Session-owned content preferences; never alter prompts or template settings."""

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import Text, cast, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.nsfw.settings import nsfw_settings, with_nsfw_settings
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay

SNAPSHOT_KEY = "__manifest_snapshot__"


class ContentPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    level: Literal["soft", "medium", "hard"]


class ContentPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    settings: ContentPreferences
    expected: ContentPreferences


class ContentSettingsConflictError(ValueError):
    """No preference changes are committed when a snapshot is missing or stale."""


def read_preferences(states: dict[str, Any] | None) -> ContentPreferences:
    snapshot = states.get(SNAPSHOT_KEY) if isinstance(states, dict) else None
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("original_manifest"), dict):
        raise ContentSettingsConflictError("This session has no valid saved adventure manifest.")
    return ContentPreferences.model_validate(nsfw_settings(snapshot["original_manifest"]))


def replace_preferences(states: dict[str, Any], preferences: ContentPreferences) -> dict[str, Any]:
    read_preferences(states)
    result = deepcopy(states)
    snapshot = result[SNAPSHOT_KEY]
    snapshot["original_manifest"] = with_nsfw_settings(
        snapshot["original_manifest"], preferences.enabled, preferences.level
    )
    return result


async def save_preferences(
    db: AsyncSession,
    state: SessionState,
    before: str | None,
    payload: ContentPreferencesUpdate,
) -> ContentPreferences:
    current = read_preferences(state.entity_states)
    if current != payload.expected:
        raise ContentSettingsConflictError(
            "Content settings changed elsewhere. Reload them before saving."
        )
    if current == payload.settings:
        return current
    replay = await db.scalar(select(TurnReplay).where(TurnReplay.session_id == state.session_id))
    if replay is not None and replay.status == "replaying":
        raise ContentSettingsConflictError(
            "A turn is being recovered. Reopen the session before saving."
        )
    replay_before = _updated_replay(replay, payload.settings)
    changed = await db.execute(
        update(SessionState)
        .where(SessionState.id == state.id, cast(SessionState.entity_states, Text) == before)
        .values(entity_states=replace_preferences(state.entity_states, payload.settings))
        .returning(SessionState.id)
        .execution_options(synchronize_session=False)
    )
    if changed.scalar_one_or_none() is None:
        raise ContentSettingsConflictError(
            "Session state changed. Reload the settings and try again."
        )
    if replay is not None and replay_before is not None:
        replay.before = replay_before
    await db.commit()
    return payload.settings


def _updated_replay(replay: TurnReplay | None, preferences: ContentPreferences) -> dict | None:
    if replay is None:
        return None
    before = deepcopy(replay.before)
    state = before.get("state") if isinstance(before, dict) else None
    if not isinstance(state, dict) or not isinstance(state.get("entity_states"), dict):
        raise ContentSettingsConflictError(
            "The saved turn snapshot is unavailable. Play a new turn first."
        )
    state["entity_states"] = replace_preferences(state["entity_states"], preferences)
    return before
