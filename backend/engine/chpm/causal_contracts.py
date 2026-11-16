"""Source-bound unfinished story threads; separate from personality and world state."""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from backend.engine.chpm.causal_graph_contracts import MAX_LINKS, FactKey
from backend.engine.chpm.core.contracts import Contract

MAX_OPEN = 3
MAX_CLOSED = 3


class Anchor(Contract):
    session_id: str
    message_id: str
    revision_id: str | None = None
    content_hash: str
    quote: str = Field(min_length=1, max_length=600)


class Fact(Contract):
    text: str = Field(min_length=1, max_length=180)
    source: Anchor


class Thread(Contract):
    id: str = Field(min_length=1, max_length=64)
    actor_id: str
    origin: Anchor
    facts: dict[FactKey, Fact] = Field(min_length=2, max_length=5)
    closure: Anchor | None = None

    @model_validator(mode="after")
    def has_purpose(self) -> "Thread":
        if "purpose" not in self.facts:
            raise ValueError("A causal thread requires its purpose.")
        return self


class Memory(Contract):
    actors: dict[str, Annotated[list[Thread], Field(max_length=MAX_OPEN + MAX_CLOSED)]] = Field(
        default_factory=dict, max_length=32
    )

    @model_validator(mode="after")
    def owned_unique_threads(self) -> "Memory":
        for actor, threads in self.actors.items():
            if any(thread.actor_id != actor for thread in threads):
                raise ValueError("Causal memory belongs to another NPC.")
            if len({thread.id for thread in threads}) != len(threads):
                raise ValueError("Causal memory repeats a thread.")
            if sum(thread.closure is None for thread in threads) > MAX_OPEN:
                raise ValueError("Too many open causal threads.")
            if sum(thread.closure is not None for thread in threads) > MAX_CLOSED:
                raise ValueError("Too many recent closed causal threads.")
        return self


class DraftFact(Contract):
    text: str = Field(min_length=1, max_length=180)
    passage_id: str = Field(min_length=1, max_length=32)


class Update(Contract):
    actor_id: str
    action: Literal["open", "update", "close"]
    thread_id: str | None = Field(default=None, min_length=1, max_length=64)
    facts: dict[FactKey, DraftFact] = Field(min_length=1, max_length=5)
    links: list[Any] = Field(default_factory=list, max_length=MAX_LINKS)

    @model_validator(mode="after")
    def explicit_target(self) -> "Update":
        if (self.action != "open") != bool(self.thread_id):
            raise ValueError("Updates/closures require an existing owned thread ID.")
        if self.action == "open" and (
            "purpose" not in self.facts or not {"cause", "event", "consequence"} & self.facts.keys()
        ):
            raise ValueError("Opening a thread needs its purpose and a grounded situation.")
        if self.action == "close" and "consequence" not in self.facts:
            raise ValueError("Closing a thread requires its explicit resulting consequence.")
        return self
