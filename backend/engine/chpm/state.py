"""Session JSON adapter: snapshots copy it; regeneration invalidates its sources."""

from typing import Any

from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import KernelState

KEY = "__chpm__"


def load(state: Any) -> KernelState:
    states = getattr(state, "entity_states", None) or {}
    raw = states.get(KEY)
    return KernelState.model_validate(raw) if raw is not None else KernelState()


def save(state: Any, value: KernelState, *, expected_revision: int) -> None:
    if load(state).revision != expected_revision:
        raise ChpmError("CHPM state changed while the model was responding. Retry the turn.")
    value = value.model_copy(deep=True)
    value.revision = expected_revision + 1
    state.entity_states = {**(state.entity_states or {}), KEY: value.model_dump(mode="json")}


def controls(state: Any, actor_id: str) -> bool:
    settings = load(state).settings
    return settings.mode == "live" and actor_id in settings.actor_ids


def retract(state: Any, message_id: str) -> None:
    current = load(state)
    if not current.actors:
        return
    # Later decisions can depend on earlier speech. Clear all derived pilot
    # decisions on a source change rather than pretending they were recomputed.
    current.actors = {}
    save(state, current, expected_revision=current.revision)
