"""Read the existing condition ledger into the observer's citable host snapshot."""

from typing import Any

from backend.engine.chpm.host_observation_contracts import HostFacts, PhysicalFact
from backend.engine.physical_conditions.ledger import read
from backend.engine.physical_conditions.schema import KEY


def capture(state: Any, actor_id: str, owned_ids: set[str]) -> tuple[PhysicalFact, ...] | None:
    states = getattr(state, "entity_states", None) or {}
    if KEY not in states:
        return None
    try:
        ledger = read(states)
    except ValueError:
        return None  # Unknown is not healed or clean.
    if not ledger.conditions and ledger.revision == 0:
        # A diagnostic-only extraction with no proposals is not an observation
        # that the NPC has no conditions. Keep legacy frames and budgets intact.
        return None
    targets = {actor_id, *owned_ids}
    rows = sorted(
        (row for row in ledger.conditions.values() if row.target_id in targets),
        key=lambda row: (row.status == "resolved", -row.updated_revision, row.id),
    )
    return tuple(
        PhysicalFact(**{key: getattr(row, key) for key in PhysicalFact.model_fields})
        for row in rows
    )


def difference(before: HostFacts, after: HostFacts) -> dict:
    if before.physical_conditions is None or after.physical_conditions is None:
        return {}
    old = {row.id: row for row in before.physical_conditions}
    current = {row.id: row for row in after.physical_conditions}
    changed = [row.model_dump(mode="json") for key, row in current.items() if old.get(key) != row]
    missing = sorted(old.keys() - current.keys())
    return {
        **({"own_physical_conditions_changed": changed} if changed else {}),
        # Loss of access, retention or corruption never establishes a completed cure.
        **({"own_physical_conditions_unavailable": missing} if missing else {}),
    }
