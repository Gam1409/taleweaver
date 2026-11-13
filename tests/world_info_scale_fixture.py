"""Fictional source-backed records spanning the full supported corpus size."""

import math
from uuid import NAMESPACE_URL, uuid5

from backend.engine.world_info.parsing import parse_source
from backend.engine.world_info.types import EntryDraft, entry_hash, searchable_text

GROUPS = ("Harbor charts", "Travel notes", "Local history", "Landmarks")


def identity(label, namespace=""):
    return str(uuid5(NAMESPACE_URL, "fictional-world-info-scale:" + namespace + ":" + label))


def _volume(start, count):
    blocks, quotes = [], []
    filler = "Reference notes.\n" * 500
    probe = parse_source(filler, "md")
    block_size = len(probe.batches[0].passages[0].text)
    for offset in range(0, count, 4):
        lines = [
            f"Archive chart {number} marks harbor route {number}."
            for number in range(start + offset, start + min(offset + 4, count))
        ]
        prefix = "\n".join(lines) + "\n"
        blocks.append((prefix + filler)[:block_size].ljust(block_size, " "))
        quotes.extend(lines)
    content = "".join(blocks)
    return content, quotes, parse_source(content, "md")


def scale_corpus(count=10_000, namespace=""):
    sources, revisions, entries = [], [], []
    for volume in range(math.ceil(count / 500)):
        start = volume * 500
        size = min(500, count - start)
        source_id, revision_id = (
            identity(f"source:{volume}", namespace),
            identity(f"revision:{volume}", namespace),
        )
        content, quotes, plan = _volume(start, size)
        sources.append(
            {
                "id": source_id,
                "title": f"Archive volume {volume + 1}",
                "filename": f"archive-{volume + 1}.md",
                "format": "md",
                "current_revision": 1,
                "published_revision": 1,
                "version": 1,
            }
        )
        revisions.append(
            {
                "id": revision_id,
                "source_id": source_id,
                "number": 1,
                "filename": f"archive-{volume + 1}.md",
                "format": "md",
                "content": content,
                "content_hash": plan.source_hash,
                "input_bytes": plan.bytes,
                "input_characters": plan.characters,
                "parser_version": 1,
                "extraction_version": 1,
                "processing_language": "English",
                "status": "review",
                "cursor": len(plan.batches),
                "total_batches": len(plan.batches),
                "processed_characters": plan.characters,
                "facts_count": size,
                "entries_count": size,
                "attempts": len(plan.batches),
                "control_version": 1,
            }
        )
        for local, quote in enumerate(quotes):
            number, batch_index = start + local, local // 4
            passage = plan.batches[batch_index].passages[0]
            position = passage.start + passage.text.index(quote)
            draft = EntryDraft(
                id=identity(f"entry:{number}", namespace),
                title=f"Chart {number}",
                summary="An archive navigation note.",
                group_name=GROUPS[number % len(GROUPS)],
                facts=[
                    {
                        "id": identity(f"fact:{number}", namespace),
                        "text": quote,
                        "original_text": quote,
                        "evidence": [
                            {
                                "passage_id": passage.id,
                                "pointer": None,
                                "start": position,
                                "end": position + len(quote),
                                "quote": quote,
                                "source_hash": plan.source_hash,
                            }
                        ],
                    }
                ],
                tags=["archive", f"coast-{number % 3}"],
            )
            entries.append(
                {
                    **draft.model_dump(mode="json"),
                    "source_id": source_id,
                    "source_revision_id": revision_id,
                    "batch_index": batch_index,
                    "ordinal": local % 4,
                    "audience": "narrator_only",
                    "known_by": [],
                    "unresolved_known_by": [],
                    "status": "published",
                    "version": 1,
                    "edited": False,
                    "search_text": searchable_text(draft),
                    "content_hash": entry_hash(draft),
                }
            )
    entries[0]["relations"] = [
        {"target_id": entries[-1]["id"], "kind": "related", "note": "Shared archive."}
    ]
    draft = EntryDraft.model_validate({key: entries[0][key] for key in EntryDraft.model_fields})
    entries[0]["content_hash"] = entry_hash(draft)
    return {"version": 1, "sources": sources, "revisions": revisions, "entries": entries}


async def seed_scale(db, session_id, user_id, count=10_000):
    """Caller owns the transaction; return IDs and samples without retaining book text."""
    from tests.world_info_fixture import seed_corpus

    payload = scale_corpus(count, namespace=session_id)
    await seed_corpus(db, session_id, user_id, payload)
    return {
        "source_ids": [row["id"] for row in payload["sources"]],
        "revision_ids": [row["id"] for row in payload["revisions"]],
        "entry_ids": [row["id"] for row in payload["entries"]],
        "samples": [payload["entries"][index] for index in sorted({0, count // 2, count - 1})],
    }
