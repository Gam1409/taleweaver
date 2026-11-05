"""Validate a complete projection before activation; replay never calls a model."""

import hashlib
import json
from functools import lru_cache
from typing import Any

from .contracts import Event, Genesis, Snapshot
from .history import events
from .reducer import TransitionError, apply, initial


def replay(genesis: Genesis, events: tuple[Event, ...]) -> Snapshot:
    return _checkpoint(genesis, events)


@lru_cache(maxsize=64)
def _checkpoint(genesis: Genesis, events: tuple[Event, ...]) -> Snapshot:
    # Keys and results are recursively frozen contracts. Cache exact content,
    # including scope/identity; never trust a caller's supplied projection.
    # Blocks bound recursion and reuse verified prefixes when a turn appends events.
    prefix = ((len(events) - 1) // 32) * 32 if events else 0
    state = _checkpoint(genesis, events[:prefix]) if prefix else initial(genesis)
    for event in events[prefix:]:
        state = apply(state, event, expected_revision=state.revision).snapshot
    return state


def restore(raw: dict[str, Any], *, expected_genesis: Genesis) -> Snapshot:
    candidate = Snapshot.model_validate(raw)
    if candidate.genesis != expected_genesis:
        raise TransitionError("Snapshot does not match the host's original identity and scope.")
    rebuilt = replay(candidate.genesis, events(candidate))
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
        tuple(event for event in events(snapshot) if event.sequence <= through_sequence),
    )


def fingerprint(snapshot: Snapshot) -> str:
    encoded = json.dumps(
        snapshot.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
