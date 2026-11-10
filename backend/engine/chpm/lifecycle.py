"""Explicit session forks and validated restore boundaries for private CHPM state."""

from copy import deepcopy

from backend.engine.chpm import agenda, causal_memory, host_observations, recent_scene
from backend.engine.chpm.core.contracts import Event, Experience, Genesis, Interpret, Observe
from backend.engine.chpm.core.history import events
from backend.engine.chpm.core.reducer import apply, initial
from backend.engine.chpm.host_state import (
    Mind,
    before_messages,
    fingerprint,
    identifier,
    payload,
    removed_messages,
)
from backend.engine.chpm.schema import KernelState, Usage
from backend.engine.chpm.state import KEY


def validate(entity_states: dict | None, session_id: str) -> dict:
    """Validate before modifying live rows; legacy saves without CHPM remain valid."""
    raw = (entity_states or {}).get(KEY)
    if raw is None:
        return entity_states or {}
    value = KernelState.model_validate(raw)
    if any(mind.genesis.scope.world_id != session_id for mind in value.minds.values()):
        raise ValueError("CHPM snapshot belongs to another session; use an explicit session copy.")
    if any(
        ref.session_id != session_id
        for threads in value.causal_memory.actors.values()
        for thread in threads
        for ref in causal_memory.anchors(thread)
    ):
        raise ValueError("Causal continuity belongs to another session; use an explicit copy.")
    return entity_states or {}


def fork(entity_states: dict | None, message_ids: dict[str, str], session_id: str) -> dict:
    """Rebind sources, then replay under the new scope without changing authored identity."""
    result = deepcopy(entity_states or {})
    if result.get(KEY) is None:
        return result
    value = KernelState.model_validate(result[KEY])
    invalid: dict[str, set[str]] = {}
    for actor, mind in value.minds.items():
        missing = {
            key
            for s in mind.sources.values()
            for key in recent_scene.dependencies(s)
            if key not in message_ids
        }
        retained = before_messages(mind, missing)
        invalid[actor] = removed_messages(mind, retained)
        value.minds[actor] = _fork_mind(retained, message_ids, session_id)
    for actor, entries in value.memories.items():
        value.memories[actor] = [
            entry.model_copy(update={"source_message_id": message_ids[entry.source_message_id]})
            for entry in entries
            if entry.source_message_id in message_ids
            and entry.source_message_id not in invalid.get(actor, set())
        ]
    retained_agenda = []
    for entry in value.agenda:
        rejected = invalid.get(entry.actor_id, set()) | {
            source.source_message_id
            for source in [entry.source] + ([entry.closure.source] if entry.closure else [])
            if source.source_message_id not in message_ids
        }
        agenda_entries = [entry]
        for message_id in rejected:
            agenda_entries = agenda.retract(agenda_entries, message_id)
        if not agenda_entries:
            continue
        retained_entry = agenda_entries[0].model_copy(deep=True)
        retained_entry.source.source_message_id = message_ids[
            retained_entry.source.source_message_id
        ]
        if retained_entry.closure:
            retained_entry.closure.source.source_message_id = message_ids[
                retained_entry.closure.source.source_message_id
            ]
        retained_agenda.append(retained_entry)
    value.agenda = retained_agenda
    for actor, rejected in invalid.items():
        for message_id in rejected:
            value.causal_memory = causal_memory.retract(
                value.causal_memory, message_id, actor_id=actor
            )
    value.causal_memory = causal_memory.fork(value.causal_memory, message_ids, session_id)
    value.causal_memory = causal_memory.rebuild(value.causal_memory, value.minds)
    # Cached decisions belong to the old input/session. Persistent identity and
    # declared goals survive; the next turn must choose its own intention anew.
    value.actors = {}
    value.last_active = {}
    value.usage = Usage()
    value.recovery.last_gap_revision = 0
    value.recovery.recent = [
        entry.model_copy(
            update={
                "input_id": message_ids[entry.input_id],
                "reply_id": message_ids[entry.reply_id],
                "reply_revision": None,
            }
        )
        for entry in value.recovery.recent
        if entry.input_id in message_ids and entry.reply_id in message_ids
    ]
    value.recovery.gap_cursors = {
        actor: min(cursor, value.minds[actor].snapshot.cursor)
        for actor, cursor in value.recovery.gap_cursors.items()
        if actor in value.minds
    }
    value.revision = 0
    result[KEY] = value.model_dump(mode="json")
    validate(result, session_id)
    return result


def _fork_mind(mind: Mind, message_ids: dict[str, str], session_id: str) -> Mind:
    genesis = Genesis(
        scope=mind.genesis.scope.model_copy(update={"world_id": session_id}),
        identity=mind.genesis.identity,
        sim_minute=mind.genesis.sim_minute,
    )
    snapshot = initial(genesis)
    sources = {}
    record_ids: dict[str, str] = {}
    for event in events(mind.snapshot):
        body = event.payload
        event_id = fingerprint({"scope": genesis.scope.model_dump(), "event": event.event_id})
        if isinstance(body, Observe):
            source = mind.sources[event.event_id]
            source = source.model_copy(update={"message_id": message_ids[source.message_id]})
            source = host_observations.remap_frame(source, message_ids)
            if source.graph:
                source = source.model_copy(
                    update={
                        "graph": source.graph.model_copy(
                            update={
                                "parents": tuple(
                                    record_ids[parent] for parent in source.graph.parents
                                ),
                                "previous": record_ids[source.graph.previous]
                                if source.graph.previous
                                else None,
                            }
                        )
                    }
                )
            event_id = identifier(source, genesis)
            changed = payload(source, genesis)
            record_ids[body.record_id] = changed.record_id
            body = changed
            sources[event_id] = source
        elif isinstance(body, (Interpret, Experience)):
            record_ids[body.record_id] = event_id
            body = body.model_copy(
                update={
                    "record_id": event_id,
                    "citations": tuple(
                        c.model_copy(update={"record_id": record_ids[c.record_id]})
                        for c in body.citations
                    ),
                }
            )
        changed_event = Event(
            scope=genesis.scope,
            event_id=event_id,
            sequence=event.sequence,
            sim_minute=event.sim_minute,
            payload=body,
        )
        snapshot = apply(snapshot, changed_event, expected_revision=snapshot.revision).snapshot
    return Mind(genesis=genesis, snapshot=snapshot, sources=sources)
