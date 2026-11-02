"""Small, version-compatible narration preferences stored with session state."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from backend.engine.visual_plan_lifecycle import reset

SETTINGS_KEY = "__vn_settings__"


class VnSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visual_preparation: Literal["legacy", "plan"] = "plan"
    visual_audit: bool = True
    visual_audit_failure: Literal["block", "warn"] = "block"
    nsfw_guard: Literal["off", "warn", "block"] = "warn"
    scene_staging: bool = False
    pace: Literal["leisurely", "balanced", "brisk"] = "balanced"

    @field_validator("visual_preparation")
    @classmethod
    def upgrade_preparation(cls, value: str) -> Literal["plan"]:
        """Accept older clients/settings while removing the selectable legacy path."""
        return "plan"


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
    old = read_settings(state)
    if (old.visual_preparation, old.visual_audit, old.visual_audit_failure) != (
        validated.visual_preparation,
        validated.visual_audit,
        validated.visual_audit_failure,
    ):
        states = reset(states)
    if read_settings(state).scene_staging != validated.scene_staging:
        states = dict(states or {})
        states.pop("__scene_staging__", None)
        states.pop("__scene_props__", None)
    state.entity_states = {
        **(states if isinstance(states, dict) else {}),
        SETTINGS_KEY: validated.model_dump(),
    }
