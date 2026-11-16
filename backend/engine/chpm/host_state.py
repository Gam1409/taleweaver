"""Host-owned identity, message provenance and the core projection in one save unit."""

import hashlib
import json
from collections.abc import Iterable
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from backend.engine.chpm.causal_graph_contracts import Binding
from backend.engine.chpm.core.contracts import Event, Genesis, Observe, Snapshot
from backend.engine.chpm.core.history import events
from backend.engine.chpm.core.limits import MAX_EVENTS
from backend.engine.chpm.core.reducer import apply
from backend.engine.chpm.core.replay import restore, rewind
from backend.engine.chpm.host_observation_contracts import HostFacts
from backend.engine.chpm.recovery_contracts import HistoricalObservation
from backend.engine.chpm.report_contracts import ReportLineage


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    message_id: str = Field(min_length=1, max_length=100)
    revision_id: str | None = None
    content_hash: str = Field(min_length=1, max_length=100)
    role: Literal["user", "assistant"]
    speaker_id: str = Field(min_length=1, max_length=100)
    kind: Literal[
        "speech",
        "narration",
        "causal_fact",
        "causal_link",
        "causal_state",
        "host_frame",
        "host_observation",
        "world_event",
    ]
    text: str = Field(min_length=1, max_length=2000)
    facts: HostFacts | None = None
    graph: Binding | None = None
    history: HistoricalObservation | None = None
    report: ReportLineage | None = None

    @model_serializer(mode="wrap")
    def legacy_shape(self, handler: SerializerFunctionWrapHandler) -> dict:
        result: dict = handler(self)
        if self.history is None:
            result.pop("history", None)
        if self.report is None:
            result.pop("report", None)
        return result

    @property
    def reported(self) -> bool:
        return self.kind in {"speech", "narration", "causal_fact", "causal_link", "causal_state"}

    @property
    def evidence_quote(self) -> str:
        return self.graph.quote if self.graph else self.text

    @model_validator(mode="after")
    def frame_facts_only(self) -> "Source":
        if self.report is not None and (
            self.role != "assistant"
            or self.kind != "speech"
            or self.report.hops[-1].observer_id != self.speaker_id
        ):
            raise ValueError("A relayed report must originate in its speaker's own knowledge.")
        if self.history is not None and (
            self.role != "assistant" or self.kind not in {"speech", "narration"}
        ):
            raise ValueError("Recovered history only binds historical narration or speech.")
        if self.facts is not None and self.kind not in {"host_frame", "host_observation"}:
            raise ValueError("Only a host frame or observation can carry authoritative state.")
        if self.kind == "host_observation":
            from backend.engine.chpm.observation_sources import validate

            validate(self)
        if (self.kind in {"causal_fact", "causal_link", "causal_state"}) != (
            self.graph is not None
        ):
            raise ValueError("Causal records require an explicit graph binding.")
        if self.graph and (
            self.role != "assistant"
            or (self.kind == "causal_fact") != (self.graph.field is not None)
            or (self.kind == "causal_state") != (self.graph.action is not None)
        ):
            raise ValueError("Causal records must have matching assistant fact/link bindings.")
        return self


class Mind(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    genesis: Genesis
    snapshot: Snapshot
    sources: dict[str, Source] = Field(default_factory=dict, max_length=MAX_EVENTS)

    @model_validator(mode="after")
    def consistent(self) -> "Mind":
        restore(self.snapshot.model_dump(), expected_genesis=self.genesis)
        observations = {
            event.event_id: event
            for event in events(self.snapshot)
            if isinstance(event.payload, Observe)
        }
        if set(observations) != set(self.sources):
            raise ValueError("Core observations must have exactly one host source binding each.")
        transitions: dict[str, str] = {}
        current_frame: Source | None = None
        for key, event in observations.items():
            source = self.sources[key]
            if source.kind == "host_frame":
                current_frame = source
            if source.kind == "host_observation":
                from backend.engine.chpm.observation_sources import validate_anchor

                validate_anchor(source, current_frame)
            if (
                source.kind == "host_observation"
                and source.speaker_id != self.genesis.scope.observer_id
            ):
                raise ValueError("A host observation belongs to another observer.")
            if event.payload != payload(source, self.genesis) or key != identifier(
                source, self.genesis
            ):
                raise ValueError("Core observation does not match its host source.")
            _validate_graph_source(source, event, self, observations)
            _validate_graph_transition(key, source, self, transitions)
        return self


def identifier(source: Source, genesis: Genesis) -> str:
    body = source.model_dump()
    # Legacy hashes included revision_id=None. Omit only the new optional field.
    if source.facts is None:
        body.pop("facts")
    if source.graph is None:
        body.pop("graph")
    return fingerprint({"scope": genesis.scope.model_dump(), "source": body})


def payload(source: Source, genesis: Genesis) -> Observe:
    root: dict = {
        "session": genesis.scope.world_id,
        "message": source.message_id,
        "revision": source.revision_id,
        "hash": source.content_hash,
        "speaker": source.speaker_id,
    }
    if source.kind == "host_frame":
        # Repeated snapshots of the same location are not independent confirmations.
        root = {"scope": genesis.scope.model_dump(), "frame": source.text}
        if source.facts is not None:
            root["facts"] = source.facts.model_dump()
    if source.kind == "host_observation":
        from backend.engine.chpm.observation_sources import signature

        root = {"scope": genesis.scope.model_dump(), "observation": signature(source.facts)}
    return Observe(
        record_id=identifier(source, genesis),
        text=source.text,
        source_kind="reported" if source.reported else "witnessed",
        root_ids=source.report.roots if source.report else (fingerprint(root),),
    )


def record(mind: Mind, source: Source, *, minute: int) -> Mind:
    return record_many(mind, [source], minute=minute)


def record_many(mind: Mind, additions: Iterable[Source], *, minute: int) -> Mind:
    """Validate the complete binding graph once after the atomic batch, never per node."""
    sources = dict(mind.sources)
    changed = mind.snapshot
    for source in additions:
        key = identifier(source, mind.genesis)
        if key in sources:
            continue
        event = Event(
            scope=mind.genesis.scope,
            event_id=key,
            sequence=changed.cursor + 1,
            sim_minute=minute,
            payload=payload(source, mind.genesis),
        )
        changed = apply(changed, event, expected_revision=changed.revision).snapshot
        sources[key] = source
    if changed is mind.snapshot:
        return mind
    return Mind(genesis=mind.genesis, snapshot=changed, sources=sources)


def _validate_graph_source(
    source: Source, event: Event, mind: Mind, observed: dict[str, Event]
) -> None:
    binding = source.graph
    if binding is None:
        return
    if source.speaker_id != mind.genesis.scope.observer_id:
        raise ValueError("Causal records belong to another observer.")
    for parent_id in binding.parents:
        parent = mind.sources.get(parent_id)
        if (
            parent is None
            or parent_id not in observed
            or observed[parent_id].sequence >= event.sequence
        ):
            raise ValueError("Causal dependencies must refer to retained earlier evidence.")
        if parent.speaker_id != source.speaker_id:
            raise ValueError("Causal dependencies belong to another NPC.")
        if source.kind == "causal_fact" and (
            parent.kind != "narration"
            or parent.text != binding.quote
            or (parent.message_id, parent.revision_id, parent.content_hash, parent.role)
            != (source.message_id, source.revision_id, source.content_hash, source.role)
        ):
            raise ValueError("A causal statement differs from its original narration.")
        if source.kind in {"causal_link", "causal_state"} and (
            parent.kind != "causal_fact"
            or parent.graph is None
            or parent.graph.thread_id != binding.thread_id
        ):
            raise ValueError("Influence endpoints must be retained facts from the same thread.")


def _validate_graph_transition(
    key: str, source: Source, mind: Mind, latest: dict[str, str]
) -> None:
    binding = source.graph
    if source.kind != "causal_state" or binding is None:
        return
    parents = [mind.sources[parent].graph for parent in binding.parents]
    fields = {parent.field for parent in parents if parent is not None}
    if "purpose" not in fields or len(fields) != len(binding.parents):
        raise ValueError("A causal transition needs its purpose and distinct fields.")
    previous = latest.get(binding.thread_id)
    if binding.previous != previous or (binding.action == "open") != (previous is None):
        raise ValueError("Causal transitions must extend the latest retained owned thread state.")
    prior_binding = mind.sources[previous].graph if previous else None
    if prior_binding and prior_binding.action == "close":
        raise ValueError("Closed causal threads cannot silently reopen.")
    latest[binding.thread_id] = key


def before_messages(mind: Mind, message_ids: set[str]) -> Mind:
    from backend.engine.chpm.recent_scene import dependencies

    removed = {key for key, source in mind.sources.items() if dependencies(source) & message_ids}
    earliest = min(
        (event.sequence for event in events(mind.snapshot) if event.event_id in removed),
        default=None,
    )
    if earliest is None:
        return mind
    changed = rewind(mind.snapshot, through_sequence=earliest - 1)
    kept = {event.event_id for event in events(changed)}
    return Mind(
        genesis=mind.genesis,
        snapshot=changed,
        sources={key: source for key, source in mind.sources.items() if key in kept},
    )


def removed_messages(before: Mind, after: Mind) -> set[str]:
    return {source.message_id for key, source in before.sources.items() if key not in after.sources}


def fingerprint(value: dict) -> str:
    body = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
