"""Canonical lossless layout; archival never summarizes accepted evidence."""

from typing import TypeVar

from .limits import ACTIVE_EVENTS, ARCHIVE_BLOCK

T = TypeVar("T")


def split(events: tuple[T, ...]) -> tuple[tuple[tuple[T, ...], ...], tuple[T, ...]]:
    blocks = []
    while len(events) > ACTIVE_EVENTS:
        blocks.append(events[:ARCHIVE_BLOCK])
        events = events[ARCHIVE_BLOCK:]
    return tuple(blocks), events
