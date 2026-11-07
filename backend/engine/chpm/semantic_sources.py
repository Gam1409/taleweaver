"""Canonical observer episodes, with exact excerpts and independently checked messages."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import digest, fingerprint
from backend.engine.memory_rag.documents import MemoryDocument
from backend.models.chat import ChatMessage

KINDS = {"speech", "narration", "world_event"}
CHUNK_CHARS = 600
STRIDE = 480


@dataclass(frozen=True)
class Episode:
    document: MemoryDocument
    record_id: str
    start: int
    evidence_order: int


async def messages(db: Any, session_id: str, ids: set[str]) -> dict[str, Any]:
    rows = {}
    ordered = sorted(ids)
    for offset in range(0, len(ordered), 400):
        found = await db.scalars(
            select(ChatMessage).where(
                ChatMessage.session_id == session_id,
                ChatMessage.id.in_(ordered[offset : offset + 400]),
            )
        )
        rows.update({row.id: row for row in found})
    return rows


def episodes(
    mind: Mind, owner: str, template_id: str | None, rows: dict[str, Any]
) -> list[Episode]:
    result = []
    scope = mind.genesis.scope
    hashes = {key: digest(row.content) for key, row in rows.items()}
    for order, evidence in enumerate(mind.snapshot.evidence):
        source = mind.sources[evidence.event_id]
        row = rows.get(source.message_id)
        if (
            source.kind not in KINDS
            or row is None
            or not _valid(source, row, hashes, scope.world_id)
        ):
            continue
        for start in range(0, len(source.text), STRIDE):
            if start and start + (CHUNK_CHARS - STRIDE) >= len(source.text):
                break
            text = source.text[start : start + CHUNK_CHARS]
            source_id = f"{scope.observer_id}:{evidence.event_id}:{start}"
            result.append(
                Episode(
                    MemoryDocument(
                        id=fingerprint(
                            {
                                "session": scope.world_id,
                                "observer": scope.observer_id,
                                "source": source_id,
                            }
                        ),
                        user_id=owner,
                        session_id=scope.world_id,
                        template_id=template_id,
                        layer="observer",
                        source_id=source_id,
                        source_hash=fingerprint(
                            {"source": source.model_dump(), "scene": row.scene_id, "start": start}
                        ),
                        npc_id=scope.observer_id,
                        scene_id=row.scene_id,
                        text=text,
                        provenance="reported" if source.reported else "witnessed",
                        source_message_ids=[source.message_id],
                        created_at=f"{order:012d}",
                    ),
                    evidence.event_id,
                    start,
                    order,
                )
            )
    return result


def _valid(source: Any, row: Any, hashes: dict[str, str], session_id: str) -> bool:
    return bool(
        row
        and (getattr(row, "npc_journal", None) or {}).get("status") != "incomplete"
        and row.session_id == session_id
        and row.role == source.role
        and row.revision_id == source.revision_id
        and hashes[row.id] == source.content_hash
        and (not source.reported or source.text in row.content)
    )


def embedding_text(episode: Episode, mind: Mind) -> str:
    doc = episode.document
    speaker = mind.sources[episode.record_id].speaker_id
    return f"Observer: {doc.npc_id}. Speaker: {speaker}. Scene: {doc.scene_id or 'unknown'}.\n{doc.text}"


def signature(base: str) -> str:
    return fingerprint({"embedding": base, "namespace": "observer-episodes-v1"})
