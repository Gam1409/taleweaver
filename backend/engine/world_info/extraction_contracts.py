"""One bounded structured proposal for facts, semantic records and their links."""

from typing import Annotated

from pydantic import Field

from backend.engine.world_info import limits
from backend.engine.world_info.types import Contract, EntryKind, RelationKind

LocalID = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")]
Tag = Annotated[str, Field(min_length=1, max_length=limits.MAX_TAG_CHARACTERS)]


class QuoteProposal(Contract):
    passage_id: str = Field(pattern=r"^p[0-9]+$")
    quote: str = Field(min_length=1, max_length=limits.MAX_EVIDENCE_CHARACTERS)


class FactProposal(Contract):
    id: LocalID
    text: str = Field(min_length=1, max_length=limits.MAX_FACT_CHARACTERS)
    evidence: list[QuoteProposal] = Field(min_length=1, max_length=limits.MAX_EVIDENCE_SPANS)


class RelationProposal(Contract):
    target_id: str = Field(min_length=1, max_length=100)
    kind: RelationKind
    note: str = Field(default="", max_length=limits.MAX_RELATION_NOTE_CHARACTERS)


class EntryProposal(Contract):
    id: LocalID
    title: str = Field(min_length=1, max_length=limits.MAX_ENTRY_TITLE_CHARACTERS)
    summary: str = Field(default="", max_length=limits.MAX_ENTRY_SUMMARY_CHARACTERS)
    group_name: str = Field(default="", max_length=limits.MAX_GROUP_CHARACTERS)
    fact_ids: list[LocalID] = Field(min_length=1, max_length=limits.MAX_ENTRY_FACTS)
    tags: list[Tag] = Field(default_factory=list, max_length=limits.MAX_TAGS)
    relations: list[RelationProposal] = Field(default_factory=list, max_length=limits.MAX_RELATIONS)
    kind: EntryKind = Field(
        default="background_lore",
        description=(
            "Source category, never proof of current state or character knowledge. Preserve rumors, "
            "attributed news and recollections separately; background_lore is the uncertain default."
        ),
    )


class ExtractionProposal(Contract):
    facts: list[FactProposal] = Field(default_factory=list, max_length=limits.MAX_BATCH_FACTS)
    entries: list[EntryProposal] = Field(default_factory=list, max_length=limits.MAX_BATCH_ENTRIES)
