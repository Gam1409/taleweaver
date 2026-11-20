"""Compose action opt-in with the existing optional pose-state owner."""

from copy import deepcopy
from types import SimpleNamespace

from backend.engine.visual_novel.config import read_settings, write_settings


def configure(states: dict, *, enabled: bool) -> dict:
    if not enabled:
        return states
    host = SimpleNamespace(entity_states=deepcopy(states))
    preferences = read_settings(host)
    if not preferences.scene_staging:
        write_settings(host, preferences.model_copy(update={"scene_staging": True}))
    result: dict = host.entity_states
    return result
