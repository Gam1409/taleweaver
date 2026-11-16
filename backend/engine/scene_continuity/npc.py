"""NPCs observe current public outcomes, never another character's private causes."""

from typing import Any

from backend.engine.chpm.host_observation_contracts import HostFacts, SceneFact

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


def difference(before: HostFacts, after: HostFacts) -> dict:
    """Record only changes in the same observed room; missing is never ended."""
    if before.scene_id != after.scene_id or before.scene_facts is None or after.scene_facts is None:
        return {}
    old = {row.id: row for row in before.scene_facts}
    current = {row.id: row for row in after.scene_facts}
    changed = [row.model_dump(mode="json") for key, row in current.items() if old.get(key) != row]
    unavailable = sorted(old.keys() - current.keys())
    return {
        **({"scene_facts_changed": changed} if changed else {}),
        **({"scene_facts_unavailable": unavailable} if unavailable else {}),
    }
