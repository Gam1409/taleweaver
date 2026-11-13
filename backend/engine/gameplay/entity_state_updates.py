"""Commit entity overrides without invalidating an active event's working state."""

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from backend.models.session_state import SessionState

_ACTIVE = "_active_event_entity_states"


@contextmanager
def entity_state_updates(state: SessionState) -> Iterator[dict[str, Any]]:
    """Publish isolated entity overrides while preserving live subsystem references.

    Reserved metadata has its own writers, including combat's cached encounter
    dictionary. Event handlers replace that metadata rather than editing it.
    Equal initial publication leaves SQLAlchemy's no-op comparison intact.
    """
    previous = getattr(state, _ACTIVE, None)
    if previous is not None:
        yield previous
        return
    working = {
        key: value if key.startswith("__") else deepcopy(value)
        for key, value in (state.entity_states or {}).items()
    }
    state.entity_states = working
    setattr(state, _ACTIVE, working)
    try:
        yield working
    finally:
        delattr(state, _ACTIVE)


def replace_entity_states(state: SessionState, updated: dict[str, Any]) -> None:
    """Publish a validated replacement while retaining the canonical mapping identity.

    Event handlers and inline callbacks share the active mapping. Outside an
    event, retain copy-on-write publication, including for shared ORM defaults.
    Callers validate locally before committing their replacement.
    """
    current = getattr(state, _ACTIVE, None)
    if current is None:
        state.entity_states = updated
    else:
        if current is not updated:
            current.clear()
            current.update(updated)
        state.entity_states = current
    flag_modified(state, "entity_states")
