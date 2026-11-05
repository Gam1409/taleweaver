"""Validate a complete projection before activation; replay never calls a model."""

import hashlib
import json
from typing import Any

from .contracts import Event, Genesis, Snapshot
from .reducer import TransitionError, apply, initial


def replay(genesis: Genesis, events: tuple[Event, ...]) -> Snapshot:
    state = initial(genesis)
    for event in events:
        state = apply(state, event, expected_revision=state.revision).snapshot
    return state


def restore(raw: dict[str, Any], *, expected_genesis: Genesis) -> Snapshot:
    candidate = Snapshot.model_validate(raw)
    if candidate.genesis != expected_genesis:
        raise TransitionError("Snapshot does not match the host's original identity and scope.")
    rebuilt = replay(candidate.genesis, candidate.journal)
    if rebuilt != candidate:
        raise TransitionError("Snapshot projection disagrees with its accepted event journal.")
    return rebuilt


def rewind(snapshot: Snapshot, *, through_sequence: int) -> Snapshot:
    if not 0 <= through_sequence <= snapshot.cursor:
        raise TransitionError("Rewind cursor is outside this snapshot.")
    # The host retains any discarded future branch separately. It is absent from
    # this active projection, including its derived beliefs and source records.
    return replay(
        snapshot.genesis,
        tuple(event for event in snapshot.journal if event.sequence <= through_sequence),
    )


def fingerprint(snapshot: Snapshot) -> str:
    encoded = json.dumps(
        snapshot.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
