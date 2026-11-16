"""Adventure defaults are copied into new sessions, never synchronized into live saves."""

from typing import Any

from backend.core.game_modes import is_vn
from backend.engine.living_world.schema import Settings, Simulation


def stored_defaults(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    return Settings.model_validate(raw).model_dump(mode="json")


def initial_state(adventure: Any) -> dict[str, Any] | None:
    raw = getattr(adventure, "living_world_settings", None)
    if raw is None or not is_vn(adventure):
        return None
    return Simulation(settings=Settings.model_validate(raw)).model_dump(mode="json")
