"""Session JSON adapter: snapshots copy it; regeneration invalidates its sources."""

from typing import Any

from pydantic import ValidationError

from backend.core.state_rejection_trace import reject
from backend.engine.chpm import agenda, causal_memory
from backend.engine.chpm.control_settings import read as control_settings
from backend.engine.chpm.host_state import before_messages, removed_messages
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import KernelState

KEY = "__chpm__"


def load(state: Any) -> KernelState:
    states = getattr(state, "entity_states", None) or {}
    raw = states.get(KEY)
    return KernelState.model_validate(raw) if raw is not None else KernelState()


def save(state: Any, value: KernelState, *, expected_revision: int) -> None:
    current = load(state)
    if current.revision != expected_revision:
        reject(
            "emotion",
            "chpm.save_stale",
            "CHPM state changed while the model was responding. Retry the turn.",
            proposal=value,
            confirmed_state=current,
            expected_revision=expected_revision,
        )
        raise ChpmError("CHPM state changed while the model was responding. Retry the turn.")
    # Mutable nested models can have bypassed their construction-time validators.
    # Validate serialized data, not an existing model instance, before replacing it.
    data = value.model_dump(mode="json")
    data["revision"] = expected_revision + 1
    try:
        checked = KernelState.model_validate(data)
    except ValidationError as exc:
        reject(
            "emotion",
            "chpm.save_invalid",
            str(exc),
            proposal=data,
            confirmed_state=current,
            validation_errors=exc.errors(include_url=False),
        )
        raise ChpmError("CHPM refused to save invalid state. Previous state is unchanged.") from exc
    state.entity_states = {**(state.entity_states or {}), KEY: checked.model_dump(mode="json")}


def controls(state: Any, actor_id: str) -> bool:
    # Selection is a settings predicate. Turn admission still calls load() to
    # validate the complete kernel before using any psychological state.
    settings = control_settings((getattr(state, "entity_states", None) or {}).get(KEY))
    return settings.mode == "live" and actor_id in settings.actor_ids


def retract(state: Any, message_id: str) -> None:
    current = load(state)
    if (
        not current.actors
        and not current.memories
        and not current.agenda
        and not current.minds
        and not current.recovery.recent
        and not current.causal_memory.actors
    ):
        return
    # Later decisions can depend on earlier speech. Clear all derived pilot
    # decisions on a source change rather than pretending they were recomputed.
    current.actors = {}
    current.last_active = {}
    actors = (
        set(current.memories)
        | set(current.minds)
        | {entry.actor_id for entry in current.agenda}
        | set(current.causal_memory.actors)
    )
    retained_agenda = []
    for actor in sorted(actors):
        invalid = {message_id}
        if actor in current.minds:
            mind = current.minds[actor]
            changed = before_messages(mind, {message_id})
            invalid.update(removed_messages(mind, changed))
            current.minds[actor] = changed
        if actor in current.memories:
            current.memories[actor] = [
                entry for entry in current.memories[actor] if entry.source_message_id not in invalid
            ]
        entries = [entry for entry in current.agenda if entry.actor_id == actor]
        for invalid_id in sorted(invalid):
            entries = agenda.retract(entries, invalid_id)
            current.causal_memory = causal_memory.retract(
                current.causal_memory, invalid_id, actor_id=actor
            )
        retained_agenda.extend(entries)
    current.agenda = retained_agenda
    current.causal_memory = causal_memory.rebuild(current.causal_memory, current.minds)
    current.recovery.recent = [
        entry
        for entry in current.recovery.recent
        if message_id not in {entry.input_id, entry.reply_id}
    ]
    current.recovery.gap_cursors = {
        actor: min(cursor, current.minds[actor].snapshot.cursor)
        for actor, cursor in current.recovery.gap_cursors.items()
        if actor in current.minds
    }
    save(state, current, expected_revision=current.revision)
