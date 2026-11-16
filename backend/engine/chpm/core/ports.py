"""The cognitive port accepts interpretations only; host stamps are not model data."""

from typing import Any

from .contracts import Event, Interpret, Snapshot, Transition
from .reducer import apply


def accept_interpretation(
    snapshot: Snapshot,
    proposal: dict[str, Any],
    *,
    event_id: str,
    sequence: int,
    sim_minute: int,
    expected_revision: int,
) -> Transition:
    # Observe/root IDs, clock commands and identity patches are not in this schema.
    # Semantics remain a fallible subjective interpretation, never world truth.
    payload = Interpret.model_validate(proposal)
    event = Event(
        scope=snapshot.genesis.scope,
        event_id=event_id,
        sequence=sequence,
        sim_minute=sim_minute,
        payload=payload,
    )
    return apply(snapshot, event, expected_revision=expected_revision)
