"""Source-bound extraction contracts shared by processing and persistence."""

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from itertools import accumulate
from types import MappingProxyType
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from backend.engine.world_info import limits

SourceFormat = Literal["md", "json"]
EntryKind = Literal[
    "background_lore",
    "reported_claim",
    "character_knowledge",
    "authored_event",
    "world_fact",
    "rumor",
    "news",
]
RelationKind = Literal["related", "supports", "contradicts", "part_of"]


def validate_text(value: str) -> str:
    """Keep original spelling while rejecting invalid Unicode and hidden controls."""
    if any(unicodedata.category(char) in {"Cs", "Cc"} and char not in "\t\r\n" for char in value):
        raise ValueError("Text contains unsupported control characters or Unicode.")
    return value


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def valid_strings(cls, value: object) -> object:
        if isinstance(value, str):
            validate_text(value)
        return value


@dataclass(frozen=True)
class SourcePassage:
    id: str
    text: str
    start: int
    end: int
    pointer: str | None = None


@dataclass(frozen=True)
class SourceBatch:
    index: int
    passages: tuple[SourcePassage, ...]


@dataclass(frozen=True)
class SourcePlan:
    format: SourceFormat
    source_hash: str
    characters: int
    bytes: int
    batches: tuple[SourceBatch, ...]

    @cached_property
    def passage_index(self) -> Mapping[str, SourcePassage]:
        """Share exact immutable locators across bulk evidence validation."""
        return MappingProxyType(
            {passage.id: passage for batch in self.batches for passage in batch.passages}
        )

    @cached_property
    def character_offsets(self) -> tuple[int, ...]:
        """Decoded processing coverage at each batch boundary, including zero."""
        sizes = (sum(len(passage.text) for passage in batch.passages) for batch in self.batches)
        return tuple(accumulate(sizes, initial=0))


class Evidence(Contract):
    passage_id: str = Field(pattern=r"^p[0-9]+$")
    pointer: str | None = Field(default=None, max_length=limits.MAX_BATCH_CHARACTERS)
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(gt=0)
    quote: str = Field(min_length=1, max_length=limits.MAX_EVIDENCE_CHARACTERS)
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def nonempty_span(self) -> "Evidence":
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError("Evidence span must match its quote length.")
        return self


class Fact(Contract):
    id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=limits.MAX_FACT_CHARACTERS)
    original_text: str = Field(min_length=1, max_length=limits.MAX_FACT_CHARACTERS)
    evidence: list[Evidence] = Field(min_length=1, max_length=limits.MAX_EVIDENCE_SPANS)
    edited: StrictBool = False

    @model_validator(mode="after")
    def mark_authored_changes(self) -> "Fact":
        if not self.text.strip() or not self.original_text.strip():
            raise ValueError("Fact statements cannot be empty.")
        if self.text != self.original_text and not self.edited:
            raise ValueError("Changed statements must retain their authored edit marker.")
        if len({(item.passage_id, item.start, item.end) for item in self.evidence}) != len(
            self.evidence
        ):
            raise ValueError("Fact evidence must contain distinct source occurrences.")
        return self


class Relation(Contract):
    target_id: str = Field(min_length=1, max_length=100)
    kind: RelationKind = "related"
    note: str = Field(default="", max_length=limits.MAX_RELATION_NOTE_CHARACTERS)


class EntryDraft(Contract):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=limits.MAX_ENTRY_TITLE_CHARACTERS)
    summary: str = Field(default="", max_length=limits.MAX_ENTRY_SUMMARY_CHARACTERS)
    group_name: str = Field(default="", max_length=limits.MAX_GROUP_CHARACTERS)
    facts: list[Fact] = Field(min_length=1, max_length=limits.MAX_ENTRY_FACTS)
    tags: list[str] = Field(default_factory=list, max_length=limits.MAX_TAGS)
    relations: list[Relation] = Field(default_factory=list, max_length=limits.MAX_RELATIONS)
    kind: EntryKind = "background_lore"

    @model_validator(mode="after")
    def bounded_entry(self) -> "EntryDraft":
        if not self.title.strip() or len({fact.id for fact in self.facts}) != len(self.facts):
            raise ValueError("Entry title and distinct fact identities are required.")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("Entry tags must be distinct.")
        for tag in self.tags:
            if not tag.strip() or len(tag) > limits.MAX_TAG_CHARACTERS:
                raise ValueError("Entry tag exceeds its text budget.")
            validate_text(tag)
        if len({(r.target_id, r.kind) for r in self.relations}) != len(self.relations):
            raise ValueError("Entry relations must be distinct.")
        if any(relation.target_id == self.id for relation in self.relations):
            raise ValueError("Entry cannot relate to itself.")
        searchable_text(self)
        return self


class EntryReference(Contract):
    """A compact reference whose session ownership is established by the caller."""

    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=limits.MAX_ENTRY_TITLE_CHARACTERS)
    group_name: str = Field(default="", max_length=limits.MAX_GROUP_CHARACTERS)


def searchable_text(entry: EntryDraft) -> str:
    """Reject oversized records instead of silently dropping approved facts."""
    text = "\n".join(
        [entry.title, entry.summary, *(fact.text for fact in entry.facts), *entry.tags]
        + ([entry.group_name] if entry.group_name else [])
    )
    if len(text) > limits.MAX_ENTRY_CHARACTERS:
        raise ValueError("Entry exceeds its searchable text budget.")
    return text


def entry_hash(entry: EntryDraft) -> str:
    payload = json.dumps(entry.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


entry_search_text = searchable_text
entry_content_hash = entry_hash
