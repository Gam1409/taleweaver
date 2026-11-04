"""Authoring detail eligibility uses existing preferences and established character age."""

from typing import Any

from backend.engine.character_identity import identity_facts
from backend.engine.clothing.settings import clothing_settings
from backend.engine.nsfw.settings import nsfw_settings


def allows_inner_layers(manifest: Any, actor: Any) -> bool:
    age = identity_facts(actor).get("age_years")
    return bool(
        nsfw_settings(manifest)["enabled"]
        and clothing_settings(manifest)["detailed"]
        and isinstance(age, int)
        and age >= 18
    )
