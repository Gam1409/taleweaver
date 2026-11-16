"""Bound diagnostics while counting every omitted note explicitly."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.engine.chpm.schema import Usage

MAX_NOTES = 20


def add(usage: "Usage", notes: list[str]) -> None:
    remaining = max(0, MAX_NOTES - len(usage.causal_notes))
    usage.causal_notes.extend(notes[:remaining])
    usage.causal_notes_omitted += max(0, len(notes) - remaining)
