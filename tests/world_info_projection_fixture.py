"""Fictional reviewed references for SQL recall and audience integration tests."""

from uuid import uuid4

from backend.engine.world_info.parsing import parse_source
from backend.engine.world_info.types import EntryDraft, Evidence, Fact, entry_hash, searchable_text
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource


async def seed_entry(
    db,
    owner,
    *,
    sid="portrait-session",
    text="The archive opens at dawn.",
    audience="narrator_only",
    known_by=(),
    status="published",
):
    plan = parse_source(text, "md")
    source = WorldInfoSource(
        user_id=owner,
        session_id=sid,
        title="Archive notes",
        filename="notes.md",
        format="md",
        published_revision=1,
        current_revision=1,
    )
    db.add(source)
    await db.flush()
    revision = WorldInfoRevision(
        source_id=source.id,
        user_id=owner,
        session_id=sid,
        number=1,
        filename=source.filename,
        format="md",
        content=text,
        content_hash=plan.source_hash,
        input_bytes=plan.bytes,
        input_characters=plan.characters,
        status="review",
    )
    db.add(revision)
    await db.flush()
    fact = Fact(
        id=str(uuid4()),
        text=text,
        original_text=text,
        evidence=[
            Evidence(
                passage_id="p0", start=0, end=len(text), quote=text, source_hash=plan.source_hash
            )
        ],
    )
    draft = EntryDraft(id=str(uuid4()), title="Archive opening", facts=[fact], tags=["archive"])
    entry = WorldInfoEntry(
        id=draft.id,
        user_id=owner,
        session_id=sid,
        source_id=source.id,
        source_revision_id=revision.id,
        batch_index=0,
        ordinal=0,
        title=draft.title,
        summary=draft.summary,
        facts=[fact.model_dump()],
        tags=draft.tags,
        relations=[],
        kind=draft.kind,
        audience=audience,
        known_by=list(known_by),
        status=status,
        search_text=searchable_text(draft),
        content_hash=entry_hash(draft),
    )
    db.add(entry)
    await db.flush()
    return source, revision, entry
