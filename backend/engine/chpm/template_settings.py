"""Adventure defaults are copied only at session creation, never into live minds."""

from typing import Any

from fastapi import HTTPException
from pydantic import model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.game_modes import is_vn
from backend.engine.chpm.capacity import required_calls
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.models.world_entity import WorldEntity


class Defaults(Settings):
    @model_validator(mode="after")
    def enough_requests(self) -> "Defaults":
        if self.mode != "off" and self.max_calls_per_turn < required_calls(self):
            raise ValueError("NPC Personality request budget must include the repair reserve.")
        return self


def stored_defaults(raw: Any) -> dict | None:
    return None if raw is None else Defaults.model_validate(raw).model_dump(mode="json")


def initial_states(adventure: Any, entity_states: dict) -> dict:
    raw = getattr(adventure, "npc_personality_settings", None)
    if raw is None or not is_vn(adventure):
        return entity_states
    settings = Defaults.model_validate(raw)
    ensure_compatible(settings, getattr(adventure, "living_world_settings", None))
    return {**entity_states, KEY: KernelState(settings=settings).model_dump(mode="json")}


def ensure_compatible(settings: Settings | None, living_world: dict | None) -> None:
    if settings and settings.mode == "live" and (living_world or {}).get("deliberation_enabled"):
        raise ValueError("Disable Living World private decisions before enabling NPC Personality.")


async def validate_update(db: AsyncSession, adventure: Any, updates: dict) -> None:
    if not {"npc_personality_settings", "living_world_settings"} & updates.keys():
        return
    raw = updates.get("npc_personality_settings", adventure.npc_personality_settings)
    settings = Defaults.model_validate(raw) if raw is not None else None
    try:
        ensure_compatible(
            settings, updates.get("living_world_settings", adventure.living_world_settings)
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if settings is None or settings.mode == "off":
        return
    ids = set(
        await db.scalars(
            select(WorldEntity.id).where(
                WorldEntity.template_id == adventure.id,
                WorldEntity.session_id.is_(None),
                WorldEntity.entity_type == "NPC",
            )
        )
    )
    if not set(settings.actor_ids) <= ids:
        raise HTTPException(422, "Choose NPCs authored in this adventure.")
