"""Small fictional source corpus shared by persistence boundary tests."""

from copy import deepcopy
from uuid import uuid4

from backend.engine.world_info.parsing import parse_source
from backend.engine.world_info.types import EntryDraft, entry_hash, searchable_text
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource


def corpus(content="assets/harbor notes: Lanterns guide ships.", format="md"):
    source_id, revision_id, replacement_id = [str(uuid4()) for _ in range(3)]
    plan = parse_source(content, format)
    passage = plan.batches[0].passages[0]
    evidence = {
        "passage_id": passage.id,
        "pointer": passage.pointer,
        "start": passage.start,
        "end": passage.start + len(passage.text),
        "quote": passage.text,
        "source_hash": plan.source_hash,
    }
    entries = []
    for ordinal in range(2):
        draft = EntryDraft(
            id=str(uuid4()),
            title=f"Harbor reference {ordinal + 1}",
            summary="A navigation note.",
            facts=[
                {
                    "id": str(uuid4()),
                    "text": "Lanterns guide ships.",
                    "original_text": "Lanterns guide ships.",
                    "evidence": [deepcopy(evidence)],
                }
            ],
            tags=["harbor"],
        )
        entries.append(
            {
                **draft.model_dump(mode="json"),
                "source_id": source_id,
                "source_revision_id": revision_id,
                "batch_index": 0,
                "ordinal": ordinal,
                "audience": "restricted" if ordinal else "common_knowledge",
                "known_by": ["NPC_NEW"] if ordinal else [],
                "status": "published",
                "version": 1,
                "edited": False,
                "search_text": searchable_text(draft),
                "content_hash": entry_hash(draft),
            }
        )
    entries[0]["relations"] = [{"target_id": entries[1]["id"], "kind": "related", "note": ""}]
    draft = EntryDraft.model_validate({key: entries[0][key] for key in EntryDraft.model_fields})
    entries[0]["content_hash"] = entry_hash(draft)
    revision = {
        "id": revision_id,
        "source_id": source_id,
        "number": 1,
        "filename": f"harbor.{format}",
        "format": format,
        "content": content,
        "content_hash": plan.source_hash,
        "input_bytes": plan.bytes,
        "input_characters": plan.characters,
        "parser_version": 1,
        "extraction_version": 1,
        "processing_language": "English",
        "status": "review",
        "cursor": 1,
        "total_batches": len(plan.batches),
        "processed_characters": sum(len(p.text) for batch in plan.batches for p in batch.passages),
        "facts_count": 2,
        "entries_count": 2,
        "attempts": 1,
        "control_version": 1,
    }
    replacement = {
        **deepcopy(revision),
        "id": replacement_id,
        "number": 2,
        "status": "processing",
        "cursor": 0,
        "processed_characters": 0,
        "facts_count": 0,
        "entries_count": 0,
    }
    return {
        "version": 1,
        "sources": [
            {
                "id": source_id,
                "title": "Harbor reference",
                "filename": f"harbor.{format}",
                "format": format,
                "current_revision": 2,
                "published_revision": 1,
                "version": 2,
            }
        ],
        "revisions": [revision, replacement],
        "entries": entries,
    }


async def seed_corpus(db, session_id, user_id, payload=None):
    payload = deepcopy(corpus() if payload is None else payload)
    for key, model in (
        ("sources", WorldInfoSource),
        ("revisions", WorldInfoRevision),
        ("entries", WorldInfoEntry),
    ):
        db.add_all(model(**row, session_id=session_id, user_id=user_id) for row in payload[key])
        await db.flush()
    return payload
