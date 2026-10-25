"""Small, version-compatible narration preferences stored with session state."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

SETTINGS_KEY = "__vn_settings__"


class VnSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pace: Literal["leisurely", "balanced", "brisk"] = "balanced"


def read_settings(state: Any) -> VnSettings:
    """Old sessions and malformed stored preferences retain conservative defaults."""
    states = getattr(state, "entity_states", None)
    raw = states.get(SETTINGS_KEY, {}) if isinstance(states, dict) else {}
    try:
        return VnSettings.model_validate(raw)
    except ValidationError:
        return VnSettings()


def write_settings(state: Any, settings: VnSettings) -> None:
    """Replace the JSON value so SQLAlchemy detects the change without touching NPCs."""
    validated = VnSettings.model_validate(settings)
    states = getattr(state, "entity_states", None)
    state.entity_states = {
        **(states if isinstance(states, dict) else {}),
        SETTINGS_KEY: validated.model_dump(),
    }
