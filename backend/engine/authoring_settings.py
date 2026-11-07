"""Preserve author-owned presentation and world briefs against generated replacements."""

from copy import deepcopy
from typing import Any

from backend.engine.blueprint.brief import BRIEF_KEY, SOURCES_KEY
from backend.engine.narrator.settings import preserve_settings as preserve_narrator_settings


def preserve_authoring_settings(manifest: dict, adventure: Any) -> dict:
    result = preserve_narrator_settings(manifest, adventure)
    previous = getattr(adventure, "original_manifest", None)
    for key in (BRIEF_KEY, SOURCES_KEY):
        result.pop(key, None)
        if isinstance(previous, dict) and key in previous:
            result[key] = deepcopy(previous[key])
    return result
