"""An enabled owner view may read facts already disclosed in ordinary narration."""

from typing import Any

from backend.engine.clothing.profiles import load_profile
from backend.engine.nsfw.settings import nsfw_settings


def enabled(state: Any, actor: dict, *, detailed: bool) -> bool:
    profile = load_profile(actor.get("visual_profile"))
    age = profile.appearance.age_years if profile else None
    snapshot = (state.entity_states or {}).get("__manifest_snapshot__") or {}
    return bool(
        detailed
        and type(age) is int
        and age >= 18
        and nsfw_settings(snapshot.get("original_manifest"))["enabled"]
    )
