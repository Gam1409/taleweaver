"""NPCs observe current public outcomes, never another character's private causes."""

from typing import Any

from backend.engine.chpm.host_observation_contracts import SceneFact

from .presentation import project
from .schema import KEY


def observations(
    state: Any, actor_id: str, targets: set[str], *, scene_description: str | None = None
) -> tuple[SceneFact, ...] | None:
    if KEY not in (getattr(state, "entity_states", None) or {}):
        return None  # Preserve the exact serialization/hashes of legacy host frames.
    data = project(state, actor_id=actor_id, targets=targets, scene_description=scene_description)
    if data["status"] == "unavailable":
        return None
    return tuple(SceneFact.model_validate(row) for row in data["facts"])
