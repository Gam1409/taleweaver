"""Rebind private intention evidence to copied messages without changing its source fences."""

from copy import deepcopy

from backend.engine.living_world.schema import Simulation


def remap_intentions(raw: dict | None, message_ids: dict[str, str]) -> dict | None:
    """Keep copied or already-rebound sources; omit intentions with no local counterpart."""
    if raw is None:
        return None
    simulation = Simulation.model_validate(deepcopy(raw))
    destinations = set(message_ids.values())
    retained = {}
    for actor, memory in simulation.dialogue_intentions.items():
        mapped = message_ids.get(memory.source_message_id)
        if mapped is None and memory.source_message_id in destinations:
            mapped = memory.source_message_id
        if mapped is None:
            continue
        memory.source_message_id = mapped
        retained[actor] = memory
    simulation.dialogue_intentions = retained
    return simulation.model_dump(mode="json")
