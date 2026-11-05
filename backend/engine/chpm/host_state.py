"""Host-owned identity, message provenance and the core projection in one save unit."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.engine.chpm.core.contracts import Event, Genesis, Observe, Snapshot
from backend.engine.chpm.core.reducer import apply
from backend.engine.chpm.core.replay import restore, rewind


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    message_id: str = Field(min_length=1, max_length=100)
    revision_id: str | None = None
    content_hash: str = Field(min_length=1, max_length=100)
    role: Literal["user", "assistant"]
    speaker_id: str = Field(min_length=1, max_length=100)
    kind: Literal["speech", "host_frame"]
    text: str = Field(min_length=1, max_length=2000)


class Mind(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    genesis: Genesis
    snapshot: Snapshot
    sources: dict[str, Source] = Field(default_factory=dict, max_length=512)

    @model_validator(mode="after")
    def consistent(self) -> "Mind":
        restore(self.snapshot.model_dump(), expected_genesis=self.genesis)
        observations = {
            event.event_id: event
            for event in self.snapshot.journal
            if isinstance(event.payload, Observe)
        }
        if set(observations) != set(self.sources):
            raise ValueError("Core observations must have exactly one host source binding each.")
        for key, event in observations.items():
            source = self.sources[key]
            if event.payload != payload(source, self.genesis) or key != identifier(
                source, self.genesis
            ):
                raise ValueError("Core observation does not match its host source.")
        return self


def identifier(source: Source, genesis: Genesis) -> str:
    return fingerprint({"scope": genesis.scope.model_dump(), "source": source.model_dump()})


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
    return Observe(
        record_id=identifier(source, genesis),
        text=source.text,
        source_kind="witnessed" if source.kind == "host_frame" else "reported",
        root_ids=(fingerprint(root),),
    )


def record(mind: Mind, source: Source, *, minute: int) -> Mind:
    key = identifier(source, mind.genesis)
    if key in mind.sources:
        return mind
    event = Event(
        scope=mind.genesis.scope,
        event_id=key,
        sequence=mind.snapshot.cursor + 1,
        sim_minute=minute,
        payload=payload(source, mind.genesis),
    )
    changed = apply(mind.snapshot, event, expected_revision=mind.snapshot.revision).snapshot
    return Mind(genesis=mind.genesis, snapshot=changed, sources={**mind.sources, key: source})


def before_messages(mind: Mind, message_ids: set[str]) -> Mind:
    removed = {key for key, source in mind.sources.items() if source.message_id in message_ids}
    earliest = min(
        (event.sequence for event in mind.snapshot.journal if event.event_id in removed),
        default=None,
    )
    if earliest is None:
        return mind
    changed = rewind(mind.snapshot, through_sequence=earliest - 1)
    kept = {event.event_id for event in changed.journal}
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
