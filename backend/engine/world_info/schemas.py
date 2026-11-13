"""Owner-facing HTTP contracts; edits cannot replace immutable source evidence."""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from backend.engine.world_info import limits
from backend.engine.world_info.types import (
    Contract,
    EntryKind,
    Fact,
    Relation,
    SourceFormat,
    validate_text,
)

Identifier = Annotated[str, Field(min_length=1, max_length=100)]
Tag = Annotated[str, Field(min_length=1, max_length=limits.MAX_TAG_CHARACTERS)]
Audience = Literal["narrator_only", "common_knowledge", "restricted"]
JobStatus = Literal["uploaded", "queued", "processing", "review", "failed", "cancelled"]
EntryStatus = Literal["draft", "published", "archived"]
EntryView = Literal["review", "active", "all"]
EntrySort = Literal["newest", "oldest", "title_asc", "title_desc", "source"]


class EntryFilters(Contract):
    view: EntryView = "review"
    source_revision_id: Identifier | None = None
    query: str = Field(default="", max_length=200)
    group_name: str | None = Field(default=None, max_length=limits.MAX_GROUP_CHARACTERS)
    tag: Tag | None = None
    kind: EntryKind | None = None
    sort: EntrySort = "newest"


class Version(Contract):
    version: StrictInt = Field(ge=1, le=limits.MAX_COUNTER - 1)


class SavedVersion(Contract):
    version: StrictInt = Field(ge=1, le=limits.MAX_COUNTER)


class ControlVersion(Contract):
    control_version: StrictInt = Field(ge=1, le=limits.MAX_COUNTER - 1)


class FactUpdate(Contract):
    id: Identifier
    text: str = Field(min_length=1, max_length=limits.MAX_FACT_CHARACTERS)

    @model_validator(mode="after")
    def nonempty(self) -> "FactUpdate":
        if not self.text.strip():
            raise ValueError("Fact text cannot be empty.")
        return self


class EntryUpdate(Version):
    title: str = Field(min_length=1, max_length=limits.MAX_ENTRY_TITLE_CHARACTERS)
    summary: str = Field(max_length=limits.MAX_ENTRY_SUMMARY_CHARACTERS)
    group_name: str | None = Field(default=None, max_length=limits.MAX_GROUP_CHARACTERS)
    kind: EntryKind
    audience: Audience
    known_by: list[Identifier] = Field(max_length=limits.MAX_KNOWN_BY)
    resolve_known_by: list[Identifier] = Field(default_factory=list, max_length=limits.MAX_KNOWN_BY)
    tags: list[Tag] = Field(max_length=limits.MAX_TAGS)
    relations: list[Relation] = Field(max_length=limits.MAX_RELATIONS)
    facts: list[FactUpdate] = Field(min_length=1, max_length=limits.MAX_ENTRY_FACTS)

    @model_validator(mode="after")
    def distinct_references(self) -> "EntryUpdate":
        if not self.title.strip():
            raise ValueError("Entry title cannot be empty.")
        for values in (
            self.known_by,
            self.resolve_known_by,
            self.tags,
            [fact.id for fact in self.facts],
        ):
            if len(values) != len(set(values)):
                raise ValueError("Entry references and tags must be distinct.")
        for tag in self.tags:
            validate_text(tag)
            if not tag.strip():
                raise ValueError("Entry tags cannot be empty.")
        if (self.audience == "restricted") != bool(self.known_by):
            raise ValueError("Only restricted entries require selected character recipients.")
        if not set(self.resolve_known_by) <= set(self.known_by):
            raise ValueError("Resolved recipients must belong to the selected recipients.")
        if len({(r.target_id, r.kind) for r in self.relations}) != len(self.relations):
            raise ValueError("Entry relations must be distinct.")
        return self


class SelectedEntry(Version):
    id: Identifier


class Publish(Contract):
    revision_id: Identifier
    source_version: StrictInt = Field(ge=1, le=limits.MAX_COUNTER - 1)
    entries: list[SelectedEntry] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def distinct_entries(self) -> "Publish":
        if len({entry.id for entry in self.entries}) != len(self.entries):
            raise ValueError("Publication entries must be distinct.")
        return self


class IndexState(Contract):
    enabled: StrictBool
    paused: StrictBool
    status: str
    desired_revision: StrictInt = Field(ge=0, le=limits.MAX_COUNTER)
    indexed_revision: StrictInt = Field(ge=0, le=limits.MAX_COUNTER)


class Job(Contract):
    id: Identifier
    source_id: Identifier
    number: StrictInt = Field(ge=1, le=limits.MAX_SOURCE_REVISIONS)
    status: JobStatus
    control_version: StrictInt = Field(ge=1, le=limits.MAX_COUNTER)
    cursor: StrictInt = Field(ge=0, le=limits.MAX_BATCHES)
    total_batches: StrictInt = Field(ge=0, le=limits.MAX_BATCHES)
    processed_characters: StrictInt = Field(ge=0, le=limits.MAX_COUNTER)
    input_bytes: StrictInt = Field(ge=1, le=limits.MAX_SOURCE_BYTES)
    input_characters: StrictInt = Field(ge=1, le=limits.MAX_SOURCE_CHARACTERS)
    facts_count: StrictInt = Field(ge=0, le=limits.MAX_SESSION_FACTS)
    entries_count: StrictInt = Field(ge=0, le=limits.MAX_SESSION_ENTRIES)
    entries_bytes: StrictInt = Field(ge=0, le=limits.MAX_COUNTER)
    entries_characters: StrictInt = Field(ge=0, le=limits.MAX_COUNTER)
    attempts: StrictInt = Field(ge=0, le=limits.MAX_COUNTER)
    processing_language: str | None
    last_error_code: str | None
    can_start: StrictBool
    can_resume: StrictBool
    can_cancel: StrictBool


class SourceView(SavedVersion):
    id: Identifier
    title: str
    filename: str
    format: SourceFormat
    current_revision: StrictInt = Field(ge=1, le=limits.MAX_SOURCE_REVISIONS)
    published_revision: StrictInt | None = Field(ge=1, le=limits.MAX_SOURCE_REVISIONS)
    published_revision_id: Identifier | None = None
    revision_count: StrictInt = Field(ge=1, le=limits.MAX_SOURCE_REVISIONS)
    active_entries: StrictInt = Field(ge=0, le=limits.MAX_SESSION_ENTRIES)
    draft_entries: StrictInt = Field(ge=0, le=limits.MAX_SESSION_ENTRIES)
    job: Job


class SourceDetail(Contract):
    source: SourceView
    revisions: list[Job]


class RevisionDetail(Contract):
    source: SourceView
    revision: Job


class RevisionContent(Contract):
    id: Identifier
    filename: str
    format: SourceFormat
    content: str = Field(max_length=limits.MAX_PREVIEW_CHARACTERS)
    content_hash: str
    input_bytes: StrictInt = Field(ge=1, le=limits.MAX_SOURCE_BYTES)
    input_characters: StrictInt = Field(ge=1, le=limits.MAX_SOURCE_CHARACTERS)
    offset: StrictInt = Field(ge=0, le=limits.MAX_SOURCE_CHARACTERS)
    next_offset: StrictInt | None = Field(ge=0, le=limits.MAX_SOURCE_CHARACTERS)
    total_characters: StrictInt = Field(ge=1, le=limits.MAX_SOURCE_CHARACTERS)


class EntrySummary(SavedVersion):
    id: Identifier
    source_id: Identifier
    source_revision_id: Identifier
    source_filename: str
    source_revision_number: StrictInt = Field(ge=1, le=limits.MAX_SOURCE_REVISIONS)
    title: str
    summary: str
    group_name: str = ""
    kind: EntryKind
    audience: Audience
    known_by: list[Identifier]
    unresolved_known_by: list[Identifier] = Field(default_factory=list)
    tags: list[str]
    status: EntryStatus
    is_active: StrictBool
    edited: StrictBool
    facts_count: StrictInt = Field(ge=1, le=limits.MAX_ENTRY_FACTS)
    character_count: StrictInt = Field(ge=0, le=limits.MAX_ENTRY_CHARACTERS)
    byte_count: StrictInt = Field(ge=0, le=limits.MAX_COUNTER)


class EntryDetail(EntrySummary):
    facts: list[Fact]
    relations: list[Relation]


class EntryPage(Contract):
    entries: list[EntrySummary]
    total: StrictInt = Field(ge=0, le=limits.MAX_SESSION_ENTRIES)
    next_offset: StrictInt | None = Field(ge=0, le=limits.MAX_COUNTER)


class FacetCount(Contract):
    name: str
    count: StrictInt = Field(ge=0, le=limits.MAX_SESSION_ENTRIES)


class FacetValues(Contract):
    items: list[FacetCount] = Field(max_length=100)
    total: StrictInt = Field(ge=0, le=limits.MAX_COUNTER)


class EntryFacets(Contract):
    groups: FacetValues
    tags: FacetValues
    kinds: FacetValues


class OverviewTotals(Contract):
    entries: StrictInt = Field(ge=0, le=limits.MAX_SESSION_ENTRIES)
    facts: StrictInt = Field(ge=0, le=limits.MAX_SESSION_FACTS)
    active_entries: StrictInt = Field(ge=0, le=limits.MAX_SESSION_ENTRIES)
    draft_entries: StrictInt = Field(ge=0, le=limits.MAX_SESSION_ENTRIES)
    archived_entries: StrictInt = Field(ge=0, le=limits.MAX_SESSION_ENTRIES)
    sources: StrictInt = Field(ge=0, le=limits.MAX_SOURCES)
    source_revisions: StrictInt = Field(ge=0, le=limits.MAX_SOURCES * limits.MAX_SOURCE_REVISIONS)
    source_bytes: StrictInt = Field(ge=0, le=limits.MAX_SESSION_SOURCE_BYTES)
    entries_bytes: StrictInt = Field(ge=0, le=limits.MAX_COUNTER)
    entries_characters: StrictInt = Field(ge=0, le=limits.MAX_COUNTER)


class Character(Contract):
    id: Identifier
    name: str


class WorldInfoLimits(Contract):
    max_source_bytes: int = limits.MAX_SOURCE_BYTES
    max_source_characters: int = limits.MAX_SOURCE_CHARACTERS
    max_sources: int = limits.MAX_SOURCES
    max_source_revisions: int = limits.MAX_SOURCE_REVISIONS
    max_session_source_bytes: int = limits.MAX_SESSION_SOURCE_BYTES
    max_entry_characters: int = limits.MAX_ENTRY_CHARACTERS
    max_entries: int = limits.MAX_SESSION_ENTRIES
    max_facts: int = limits.MAX_SESSION_FACTS
    max_group_characters: int = limits.MAX_GROUP_CHARACTERS
    max_entry_title_characters: int = limits.MAX_ENTRY_TITLE_CHARACTERS
    max_entry_summary_characters: int = limits.MAX_ENTRY_SUMMARY_CHARACTERS
    max_fact_characters: int = limits.MAX_FACT_CHARACTERS
    max_tags: int = limits.MAX_TAGS
    max_tag_characters: int = limits.MAX_TAG_CHARACTERS
    max_known_by: int = limits.MAX_KNOWN_BY
    max_relations: int = limits.MAX_RELATIONS
    max_relation_note_characters: int = limits.MAX_RELATION_NOTE_CHARACTERS


class WorldInfoOverview(Contract):
    session_id: Identifier
    sources: list[SourceView]
    characters: list[Character]
    index: IndexState
    limits: WorldInfoLimits
    totals: OverviewTotals
