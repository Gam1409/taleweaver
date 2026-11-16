"""Transient scene inputs already loaded by the foreground turn pipeline."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SceneScope:
    scene_id: str
    targets: frozenset[str]
    description: str
    entities: tuple[Any, ...]
    item_state_entities: tuple[Any, ...] | None = None
