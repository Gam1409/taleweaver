"""One chronological view over exact archive blocks and the active journal."""

from itertools import chain

from .contracts import Event, Snapshot


def events(snapshot: Snapshot) -> tuple[Event, ...]:
    return tuple(chain.from_iterable(block.events for block in snapshot.archive)) + snapshot.journal


def count(snapshot: Snapshot) -> int:
    return sum(len(block.events) for block in snapshot.archive) + len(snapshot.journal)
