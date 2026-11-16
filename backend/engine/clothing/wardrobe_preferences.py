"""Explicit debug edits of session clothing detail and a session NPC's recorded age."""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.character_identity import identity_facts, update_identity
from backend.engine.clothing.recovery_context import KEY
from backend.engine.clothing.settings import with_clothing_settings
from backend.engine.clothing.visuals import detailed_for_state
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from backend.schemas.character_identity import CharacterIdentityFields


class WardrobePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detailed: StrictBool
    age_years: StrictInt | None = Field(ge=0, le=100000)


class PreferencesEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    npc_id: str = Field(min_length=1, max_length=100)
    expected: WardrobePreferences
    settings: WardrobePreferences


def read_preferences(npc: Any, states: dict) -> dict:
    return {
        "detailed": detailed_for_state(SimpleNamespace(entity_states=states)),
        "age_years": identity_facts(npc).get("age_years"),
    }


async def debug_wardrobe_settings(
    db: AsyncSession,
    state: SessionState,
    args: str,
    user: Any = None,
    adventure: Any = None,
    avatar: Any = None,
) -> str:
    if not state.is_debug_enabled:
        return "DEBUG ERROR: Enable debug mode first."
    try:
        edit = PreferencesEdit.model_validate_json(args.partition(" ")[2])
        return await _save_preferences(db, state, edit)
    except ValidationError:
        return "DEBUG ERROR: Invalid wardrobe settings. Use a boolean for layer tracking and an integer age from 0 to 100000, or null for unknown."
    except ValueError as exc:
        return f"DEBUG ERROR: {exc}"


async def _save_preferences(db: AsyncSession, state: SessionState, edit: PreferencesEdit) -> str:
    npc = await db.scalar(
        select(WorldEntity).where(
            WorldEntity.session_id == state.session_id,
            WorldEntity.id == edit.npc_id,
            WorldEntity.entity_type == "NPC",
        )
    )
    if npc is None:
        raise ValueError("NPC does not belong to this session.")
    states = deepcopy(state.entity_states or {})
    current = WardrobePreferences.model_validate(read_preferences(npc, states))
    if current != edit.expected:
        raise ValueError("Wardrobe settings changed. Refresh the debug inspector before saving.")
    if current == edit.settings:
        return "DEBUG: Wardrobe settings are already up to date."
    snapshot = states.get("__manifest_snapshot__")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("original_manifest"), dict):
        raise ValueError(
            "The session has no valid saved manifest; clothing settings cannot be updated."
        )
    snapshot["original_manifest"] = with_clothing_settings(
        snapshot["original_manifest"], edit.settings.detailed
    )
    override = states.get(npc.id) or {}
    profile = override.get("visual_profile")
    if isinstance(profile, dict) and isinstance(profile.get("appearance", {}), dict):
        profile["appearance"] = {
            **profile.get("appearance", {}),
            "age_years": edit.settings.age_years,
        }
    update_identity(npc, CharacterIdentityFields(age_years=edit.settings.age_years))
    states.pop(KEY, None)
    state.entity_states = states
    return f"DEBUG: Saved this session's clothing detail and {npc.name}'s recorded age. Generate a new wardrobe preview."
