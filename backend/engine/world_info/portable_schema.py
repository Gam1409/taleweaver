"""Validate portable knowledge before assigning destination ownership or writing rows."""

from collections import Counter
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from backend.core.content_language import normalize_language
from backend.engine.world_info import limits
from backend.engine.world_info.capacity import validate_entry_capacity
from backend.engine.world_info.parsing import parse_source, validate_evidence
from backend.engine.world_info.types import (
    Contract,
    EntryDraft,
    SourceFormat,
    SourcePlan,
    entry_hash,
    searchable_text,
)


class PortableRow(Contract):
    id: str = Field(min_length=1, max_length=36)
    # Legacy/exported ownership is informational; the importer always assigns its caller.
    user_id: str | None = None
    session_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PortableSource(PortableRow):
    title: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=255)
    format: SourceFormat
    current_revision: StrictInt = Field(ge=1, le=limits.MAX_SOURCE_REVISIONS)
    published_revision: StrictInt | None = Field(default=None, ge=1, le=limits.MAX_SOURCE_REVISIONS)
    version: StrictInt = Field(ge=1, le=limits.MAX_COUNTER)


class PortableRevision(PortableRow):
    source_id: str = Field(min_length=1, max_length=36)
    number: StrictInt = Field(ge=1, le=limits.MAX_SOURCE_REVISIONS)
    filename: str = Field(min_length=1, max_length=255)
    format: SourceFormat
    content: str = Field(min_length=1, max_length=limits.MAX_SOURCE_CHARACTERS)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_bytes: StrictInt = Field(ge=1, le=limits.MAX_SOURCE_BYTES)
    input_characters: StrictInt = Field(ge=1, le=limits.MAX_SOURCE_CHARACTERS)
    parser_version: StrictInt = Field(ge=1, le=limits.PARSER_VERSION)
    extraction_version: StrictInt = Field(ge=1, le=limits.EXTRACTION_VERSION)
    processing_language: str | None = Field(default=None, max_length=40)
    status: Literal["uploaded", "queued", "processing", "review", "failed", "cancelled"]
    cursor: StrictInt = Field(ge=0, le=limits.MAX_BATCHES)
    total_batches: StrictInt = Field(ge=0, le=limits.MAX_BATCHES)
    processed_characters: StrictInt = Field(
        ge=0, le=limits.MAX_BATCHES * limits.MAX_BATCH_CHARACTERS
    )
    facts_count: StrictInt = Field(ge=0, le=limits.MAX_SESSION_FACTS)
    entries_count: StrictInt = Field(ge=0, le=limits.MAX_SESSION_ENTRIES)
    attempts: StrictInt = Field(ge=0, le=limits.MAX_COUNTER)
    control_version: StrictInt = Field(ge=1, le=limits.MAX_COUNTER)
    last_error_code: str | None = Field(default=None, pattern=r"^[a-z_]{1,64}$")

    @field_validator("processing_language")
    @classmethod
    def normalized_language(cls, value: str | None) -> str | None:
        if value is not None and normalize_language(value) != value:
            raise ValueError(
                "World Info processing language must be a supported normalized language."
            )
        return value


class PortableEntry(PortableRow, EntryDraft):
    group_name: str = Field(default="", max_length=limits.MAX_GROUP_CHARACTERS)
    source_id: str = Field(min_length=1, max_length=36)
    source_revision_id: str = Field(min_length=1, max_length=36)
    batch_index: StrictInt = Field(ge=0, lt=limits.MAX_BATCHES)
    ordinal: StrictInt = Field(ge=0, lt=limits.MAX_BATCH_ENTRIES)
    audience: Literal["narrator_only", "common_knowledge", "restricted"]
    known_by: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        max_length=limits.MAX_KNOWN_BY
    )
    unresolved_known_by: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=limits.MAX_KNOWN_BY
    )
    status: Literal["draft", "published", "archived"]
    version: StrictInt = Field(ge=1, le=limits.MAX_COUNTER)
    search_text: str = Field(max_length=limits.MAX_ENTRY_CHARACTERS)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    edited: StrictBool = False


def entry_draft(entry: PortableEntry) -> EntryDraft:
    return EntryDraft.model_validate({key: getattr(entry, key) for key in EntryDraft.model_fields})


def _distinct(rows: list[Any], label: str) -> dict[str, Any]:
    mapped = {row.id: row for row in rows}
    if len(mapped) != len(rows):
        raise ValueError(f"Duplicate World Info {label} identity.")
    return mapped


def _validated_plan(revision: PortableRevision) -> SourcePlan:
    plan = parse_source(revision.content, revision.format)
    if (revision.content_hash, revision.input_bytes, revision.input_characters) != (
        plan.source_hash,
        plan.bytes,
        plan.characters,
    ):
        raise ValueError("World Info source checksum or size differs from its content.")
    if (
        revision.cursor > revision.total_batches
        or revision.total_batches not in {0, len(plan.batches)}
        or revision.total_batches == 0
        and revision.cursor != 0
    ):
        raise ValueError("World Info processing progress is invalid.")
    if revision.processing_language is None and (
        revision.cursor > 0 or revision.status in {"queued", "processing", "review"}
    ):
        raise ValueError("World Info processing progress requires a frozen content language.")
    processed = sum(
        len(passage.text) for batch in plan.batches[: revision.cursor] for passage in batch.passages
    )
    if revision.processed_characters != processed:
        raise ValueError("World Info processing character count differs from completed batches.")
    return plan


class PortableWorldInfo(Contract):
    version: StrictInt = Field(default=1, ge=1, le=1)
    sources: list[PortableSource] = Field(default_factory=list, max_length=limits.MAX_SOURCES)
    revisions: list[PortableRevision] = Field(
        default_factory=list, max_length=limits.MAX_SOURCES * limits.MAX_SOURCE_REVISIONS
    )
    entries: list[PortableEntry] = Field(
        default_factory=list, max_length=limits.MAX_SESSION_ENTRIES
    )

    @model_validator(mode="after")
    def validate_graph(self) -> "PortableWorldInfo":
        sources = _distinct(self.sources, "source")
        revisions = _distinct(self.revisions, "revision")
        entries = _distinct(self.entries, "entry")
        validate_entry_capacity(self.entries)
        if sum(row.input_bytes for row in self.revisions) > limits.MAX_SESSION_SOURCE_BYTES:
            raise ValueError("World Info exceeds its stored source byte budget.")
        facts = [fact for row in self.entries for fact in row.facts]
        if len(facts) > limits.MAX_SESSION_FACTS or len({fact.id for fact in facts}) != len(facts):
            raise ValueError("World Info exceeds its fact budget or repeats fact identities.")
        plans = self._revisions(sources)
        self._entries(revisions, entries, plans)
        return self

    def _revisions(self, sources: dict) -> dict:
        plans, numbers = {}, {}
        for revision in self.revisions:
            if revision.source_id not in sources:
                raise ValueError("World Info revision references an unknown source.")
            key = revision.source_id, revision.number
            if key in numbers:
                raise ValueError("Duplicate World Info source revision number.")
            numbers[key] = revision
            plans[revision.id] = _validated_plan(revision)
        for source in self.sources:
            current = numbers.get((source.id, source.current_revision))
            if current is None or (source.filename, source.format) != (
                current.filename,
                current.format,
            ):
                raise ValueError("World Info current revision is missing or mismatched.")
            if source.published_revision is not None and (
                source.published_revision > source.current_revision
                or (source.id, source.published_revision) not in numbers
            ):
                raise ValueError("World Info published revision is missing.")
            if any(number > source.current_revision for sid, number in numbers if sid == source.id):
                raise ValueError("World Info source has a future revision.")
        return plans

    def _entries(self, revisions: dict, entries: dict, plans: dict) -> None:
        positions: set[tuple[str, int, int]] = set()
        for entry in self.entries:
            revision = revisions.get(entry.source_revision_id)
            if revision is None or revision.source_id != entry.source_id:
                raise ValueError("World Info entry references another source or revision.")
            if entry.batch_index >= revision.cursor:
                raise ValueError("World Info entry occupies an unprocessed batch.")
            position = entry.source_revision_id, entry.batch_index, entry.ordinal
            if position in positions:
                raise ValueError("Duplicate World Info batch entry position.")
            positions.add(position)
            self._entry(entry, plans[revision.id], entries)
        entry_counts = Counter(row.source_revision_id for row in self.entries)
        fact_counts = Counter(row.source_revision_id for row in self.entries for _ in row.facts)
        for revision in self.revisions:
            if (revision.entries_count, revision.facts_count) != (
                entry_counts[revision.id],
                fact_counts[revision.id],
            ):
                raise ValueError("World Info saved entry counts are inconsistent.")

    @staticmethod
    def _entry(entry: PortableEntry, plan: Any, entries: dict) -> None:
        draft = entry_draft(entry)
        if entry.search_text != searchable_text(draft) or entry.content_hash != entry_hash(draft):
            raise ValueError("World Info derived entry data differs from its content.")
        if entry.batch_index >= len(plan.batches):
            raise ValueError("World Info entry references an unknown batch.")
        passages = {passage.id for passage in plan.batches[entry.batch_index].passages}
        for evidence in (evidence for fact in entry.facts for evidence in fact.evidence):
            validate_evidence(evidence, plan)
            if evidence.passage_id not in passages:
                raise ValueError("World Info evidence belongs to another processing batch.")
        if any(relation.target_id not in entries for relation in entry.relations):
            raise ValueError("World Info relation references an unknown entry.")
        if len(set(entry.known_by)) != len(entry.known_by):
            raise ValueError("World Info recipient identities must be distinct.")
        if len(set(entry.unresolved_known_by)) != len(entry.unresolved_known_by) or set(
            entry.unresolved_known_by
        ) - set(entry.known_by):
            raise ValueError(
                "World Info unresolved recipients must be distinct assigned identities."
            )
        if (entry.audience == "restricted") != bool(entry.known_by):
            raise ValueError("World Info restricted audience requires explicit recipients.")
