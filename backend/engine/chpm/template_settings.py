"""Adventure defaults are copied only at session creation, never into live minds."""

from typing import Any

from fastapi import HTTPException
from pydantic import model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.game_modes import mode_policy
from backend.engine.chpm.capacity import required_calls
from backend.engine.chpm.schema import KernelState, Settings, SettingsFields
from backend.engine.chpm.state import KEY
from backend.engine.npc_actions.settings import configure as configure_actions
from backend.models.world_entity import WorldEntity


class Defaults(Settings):
    @model_validator(mode="after")
    def enough_requests(self) -> "Defaults":
        if self.mode != "off" and self.max_calls_per_turn < required_calls(self):
            raise ValueError("NPC Personality request budget must include the repair reserve.")
        return self


def settings_for_mode(raw: Any, mode: str | None) -> Settings:
    """Derive controller authority from the host, before inspecting budgets or conflicts."""
    values = raw.model_dump() if isinstance(raw, Settings) else raw
    if not isinstance(values, dict):
        return Settings.model_validate(values)
    host_mode = mode_policy(mode).mode
    settings = Settings.model_validate(
        {**values, "control_scope": "combat_actions" if host_mode == "rpg" else "dialogue"}
    )
    if settings.mode != "off" and host_mode not in {"vn", "rpg"}:
        raise ValueError("NPC Personality requires a Visual Novel or RPG combat session.")
    return settings


def _dormant_defaults(raw: Any, mode: str) -> Defaults | None:
    """Older non-VN templates could retain inactive dialogue preferences."""
    values = raw.model_dump() if isinstance(raw, Settings) else raw
    if (
        mode == "vn"
        or not isinstance(values, dict)
        or values.get("control_scope", "dialogue") != "dialogue"
        or values.get("action_tools", False)
    ):
        return None
    return Defaults.model_validate(values)


def stored_defaults(
    raw: Any,
    *,
    mode: str | None,
    living_world: dict | None = None,
    preserve_saved: bool = False,
) -> dict | None:
    """Keep saved opt-ins and budgets; explicit authoring requires current admission."""
    if raw is None:
        return None
    host_mode = mode_policy(mode).mode
    dormant = _dormant_defaults(raw, host_mode) if preserve_saved else None
    if dormant is not None:
        return dormant.model_dump(mode="json")
    settings = settings_for_mode(raw, host_mode)
    if not preserve_saved or host_mode != "rpg":
        settings = Defaults.model_validate(settings.model_dump())
    ensure_compatible(settings, living_world)
    return settings.model_dump(mode="json")


def initial_states(adventure: Any, entity_states: dict) -> dict:
    raw = getattr(adventure, "npc_personality_settings", None)
    if raw is None:
        return entity_states
    mode = mode_policy(getattr(adventure, "rule_enforcement_mode", None)).mode
    if _dormant_defaults(raw, mode) is not None:
        return entity_states
    if mode not in {"vn", "rpg"} and isinstance(raw, dict) and raw.get("mode", "off") == "off":
        Settings.model_validate(raw)
        return entity_states
    settings = settings_for_mode(raw, mode)
    if mode != "rpg":
        settings = Defaults.model_validate(settings.model_dump())
    ensure_compatible(settings, getattr(adventure, "living_world_settings", None))
    return configure_actions(
        {**entity_states, KEY: KernelState(settings=settings).model_dump(mode="json")},
        enabled=settings.control_scope == "dialogue"
        and settings.action_tools
        and settings.mode == "live",
    )


def ensure_compatible(settings: Settings | None, living_world: dict | None) -> None:
    if not settings or settings.mode != "live" or settings.control_scope != "dialogue":
        return
    from backend.engine.living_world.schema import Settings as LivingWorldSettings

    if LivingWorldSettings.model_validate(living_world or {}).private_decisions_active:
        raise ValueError("Disable Living World private decisions before enabling NPC Personality.")


def ensure_session_compatible(state: Any, settings: Settings | None = None) -> None:
    """Restored session flags must obey the same rule as owner-facing controls."""
    raw = getattr(state, "living_world", None)
    if not raw:
        return
    from backend.engine.chpm.control_settings import read
    from backend.engine.living_world.schema import Settings as LivingWorldSettings

    settings = settings or read((state.entity_states or {}).get(KEY))
    if settings.mode != "live":
        return
    if not isinstance(raw, dict):
        raise ValueError("Living World controller settings are unavailable.")
    living_world = LivingWorldSettings.model_validate(raw.get("settings", {}))
    ensure_compatible(settings, living_world.model_dump(mode="json"))


def _defaults_changed(adventure: Any, raw: Any, mode: str | None) -> bool:
    """Full editor payloads are round trips until settings or host authority actually change."""
    if mode_policy(mode).mode != mode_policy(adventure.rule_enforcement_mode).mode:
        return True
    previous = adventure.npc_personality_settings
    if raw is None or previous is None:
        return raw is not previous
    # Compare the closed input fields before host rebinding. New policy checks
    # still run through stored_defaults; stale client scope cannot choose authority.
    proposed = SettingsFields.model_validate(raw).model_dump(mode="json")
    try:
        saved = SettingsFields.model_validate(previous).model_dump(mode="json")
    except ValueError:
        # A malformed historical value must not prevent its valid replacement.
        return True
    return proposed != saved


async def validate_update(db: AsyncSession, adventure: Any, updates: dict) -> None:
    triggers = {"npc_personality_settings", "living_world_settings", "rule_enforcement_mode"}
    if not triggers & updates.keys():
        return
    raw = updates.get("npc_personality_settings", adventure.npc_personality_settings)
    mode = updates.get("rule_enforcement_mode", adventure.rule_enforcement_mode)
    try:
        normalized = stored_defaults(
            raw,
            mode=mode,
            living_world=updates.get("living_world_settings", adventure.living_world_settings),
            preserve_saved=not _defaults_changed(adventure, raw, mode),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if normalized is not None or "npc_personality_settings" in updates:
        updates["npc_personality_settings"] = normalized
    settings = Settings.model_validate(normalized) if normalized is not None else None
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
