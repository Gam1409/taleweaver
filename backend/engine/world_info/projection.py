"""Published session references projected from SQL, never from vector payloads."""

import json
from collections.abc import Collection
from typing import Any, get_args
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert

from backend.engine.memory_rag.documents import MemoryDocument, content_hash
from backend.engine.memory_rag.ranking import ordered_terms
from backend.engine.world_info import limits
from backend.engine.world_info.types import EntryDraft, EntryKind, searchable_text
from backend.models.game_session import GameSession
from backend.models.world_entity import WorldEntity
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource

LAYER = "world_info"
RECENT_ENTRIES = 16
LEXICAL_ENTRIES = 32
SEMANTIC_ENTRIES = 32
_AUDIENCES = {"narrator_only", "common_knowledge", "restricted"}
_KINDS = frozenset(get_args(EntryKind))


def visible_to(
    document: MemoryDocument,
    audience: str,
    *,
    actor_id: str | None = None,
    actual_npc_ids: Collection[str] = (),
) -> bool:
    """Imported references never become mechanics or witnessed observer evidence."""
    if document.layer != LAYER:
        return True
    if document.audience not in _AUDIENCES or document.reference_kind not in _KINDS:
        return False
    if audience == "narrator":
        return True
    if audience in {"vn_continuity", "vn_social"}:
        return document.audience == "common_knowledge"
    if audience != "actor" or not actor_id or actor_id not in actual_npc_ids:
        return False
    return document.audience == "common_knowledge" or (
        document.audience == "restricted"
        and actor_id in document.known_by
        and actor_id not in document.unresolved_known_by
    )


def _published(user_id: str, session_id: str) -> Any:
    return (
        select(
            WorldInfoEntry,
            WorldInfoSource,
            WorldInfoRevision.id,
            WorldInfoRevision.number,
            WorldInfoRevision.content_hash,
            WorldInfoRevision.filename,
        )
        .join(WorldInfoSource, WorldInfoSource.id == WorldInfoEntry.source_id)
        .join(
            WorldInfoRevision,
            (WorldInfoRevision.id == WorldInfoEntry.source_revision_id)
            & (WorldInfoRevision.source_id == WorldInfoSource.id),
        )
        .join(GameSession, GameSession.id == WorldInfoEntry.session_id)
        .where(
            GameSession.user_id == user_id,
            WorldInfoEntry.user_id == user_id,
            WorldInfoEntry.session_id == session_id,
            WorldInfoSource.user_id == user_id,
            WorldInfoSource.session_id == session_id,
            WorldInfoRevision.user_id == user_id,
            WorldInfoRevision.session_id == session_id,
            WorldInfoSource.published_revision == WorldInfoRevision.number,
            WorldInfoEntry.status == "published",
        )
        .execution_options(populate_existing=True)
    )


def _candidate_ids(candidates: list[dict]) -> list[str]:
    identifiers = []
    for row in candidates[:SEMANTIC_ENTRIES]:
        prefix, _, identifier = str(row.get("source_id") or "").partition(":")
        if row.get("layer") != LAYER or prefix != LAYER:
            continue
        try:
            identifiers.append(str(UUID(identifier)))
        except ValueError:
            continue
    return list(dict.fromkeys(identifiers))


async def _lexical_rows(db: Any, ordered: Any, terms: list[str]) -> list[Any]:
    """Reserve each term a share before broad context can fill the lexical bound."""
    selected: dict[str, Any] = {}
    per_term = LEXICAL_ENTRIES // len(terms)
    for term in terms:
        rows = await db.execute(
            ordered.where(
                WorldInfoEntry.id.not_in(list(selected)),
                func.tw_contains_any(
                    WorldInfoEntry.search_text, json.dumps([term], ensure_ascii=False)
                )
                == 1,
            ).limit(per_term)
        )
        selected.update({row[0].id: row for row in rows.all()})
    remaining = LEXICAL_ENTRIES - len(selected)
    if remaining:
        rows = await db.execute(
            ordered.where(
                WorldInfoEntry.id.not_in(list(selected)),
                func.tw_contains_any(
                    WorldInfoEntry.search_text, json.dumps(terms, ensure_ascii=False)
                )
                == 1,
            ).limit(remaining)
        )
        selected.update({row[0].id: row for row in rows.all()})
    return list(selected.values())


async def collect_documents(
    db: Any,
    state: Any,
    user_id: str,
    *,
    query: str | None = None,
    candidates: list[dict] | None = None,
) -> list[MemoryDocument]:
    """Full idle corpus, or bounded fresh/lexical/candidate rows for foreground recall."""
    base = _published(user_id, state.session_id)
    ordered = base.order_by(WorldInfoEntry.updated_at.desc(), WorldInfoEntry.id)
    if query is None:
        rows = list((await db.execute(ordered.limit(limits.MAX_SESSION_ENTRIES))).all())
    else:
        rows = list((await db.execute(ordered.limit(RECENT_ENTRIES))).all())
        terms = ordered_terms(query, 8, minimum=3)
        if terms:
            rows.extend(await _lexical_rows(db, ordered, terms))
        identifiers = _candidate_ids(candidates or [])
        if identifiers:
            rows.extend((await db.execute(base.where(WorldInfoEntry.id.in_(identifiers)))).all())
    rows = list({row[0].id: row for row in rows}.values())
    actual = await _recipients(db, state.session_id, rows)
    documents = [_document(state, user_id, row, actual) for row in rows]
    return [document for document in documents if document is not None]


async def _recipients(db: Any, session_id: str, rows: list[Any]) -> set[str]:
    wanted = sorted(
        {
            recipient
            for row in rows
            if row[0].audience == "restricted" and _valid_audience(row[0])
            for recipient in row[0].known_by
        }
    )
    if not wanted:
        return set()
    # One bounded JSON parameter avoids SQLite's variable limit for large idle corpora.
    identifiers = func.json_each(json.dumps(wanted, ensure_ascii=False)).table_valued("value")
    return set(
        await db.scalars(
            select(WorldEntity.id).where(
                WorldEntity.session_id == session_id,
                WorldEntity.entity_type == "NPC",
                WorldEntity.id.in_(select(identifiers.c.value)),
            )
        )
    )


def _document(
    state: Any, user_id: str, row: Any, actual_npc_ids: set[str]
) -> MemoryDocument | None:
    entry, source, revision_id, number, source_hash, filename = row
    try:
        draft = EntryDraft.model_validate(
            {key: getattr(entry, key) for key in EntryDraft.model_fields}
        )
        text = searchable_text(draft)
    except ValueError:
        return None
    if not _valid_audience(entry):
        return None
    if any(
        evidence.source_hash != source_hash for fact in draft.facts for evidence in fact.evidence
    ):
        return None
    source_id = f"{LAYER}:{entry.id}"
    known_by = tuple(sorted(entry.known_by))
    stored_unresolved = tuple(sorted(getattr(entry, "unresolved_known_by", [])))
    unresolved = tuple(sorted(set(stored_unresolved) | (set(known_by) - actual_npc_ids)))
    attribution = {"id": source.id, "revision": number, "title": source.title, "filename": filename}
    fingerprint = content_hash(
        [
            "world-info-reference-v1",
            user_id,
            state.session_id,
            draft.model_dump(mode="json"),
            entry.version,
            entry.audience,
            known_by,
            stored_unresolved,
            unresolved,
            entry.edited,
            source.published_revision,
            source_hash,
            revision_id,
            attribution,
        ]
    )
    return MemoryDocument(
        id=content_hash([user_id, state.session_id, LAYER, source_id]),
        user_id=user_id,
        session_id=state.session_id,
        template_id=state.template_id,
        layer=LAYER,
        source_id=source_id,
        source_hash=fingerprint,
        npc_id=None,
        scene_id=None,
        text=text,
        provenance="authored_reference",
        source_message_ids=[],
        created_at=entry.updated_at.isoformat(),
        reference_kind=draft.kind,
        audience=entry.audience,
        known_by=known_by,
        unresolved_known_by=unresolved,
        source_attribution=attribution,
        reference_edited=entry.edited or any(fact.edited for fact in draft.facts),
        reference_relations=tuple(
            (relation.kind, f"{LAYER}:{relation.target_id}") for relation in draft.relations
        ),
    )


def _valid_audience(entry: Any) -> bool:
    recipients = entry.known_by
    unresolved = getattr(entry, "unresolved_known_by", [])
    if (
        entry.audience not in _AUDIENCES
        or not isinstance(recipients, list)
        or len(recipients) > limits.MAX_KNOWN_BY
        or any(not isinstance(recipient, str) for recipient in recipients)
        or not isinstance(unresolved, list)
        or len(unresolved) > limits.MAX_KNOWN_BY
        or any(not isinstance(recipient, str) for recipient in unresolved)
    ):
        return False
    if (
        len(set(recipients)) != len(recipients)
        or len(set(unresolved)) != len(unresolved)
        or not set(unresolved) <= set(recipients)
    ):
        return False
    if entry.audience == "restricted":
        return bool(recipients)
    return not recipients


async def mark_changed(db: Any, user_id: str, session_id: str) -> None:
    """Join publication's transaction; fence derived work without unpausing recall."""
    from backend.engine.memory_rag.control import invalidate
    from backend.models.memory_rag import MemoryIndexState

    session = await db.scalar(
        select(GameSession).where(GameSession.id == session_id, GameSession.user_id == user_id)
    )
    if session is None:
        raise ValueError("Session reference ownership is unavailable.")
    await db.execute(
        insert(MemoryIndexState)
        .values(session_id=session_id, user_id=user_id, template_id=session.template_id)
        .on_conflict_do_nothing(index_elements=[MemoryIndexState.session_id])
    )
    row = await db.scalar(
        select(MemoryIndexState).where(
            MemoryIndexState.session_id == session_id, MemoryIndexState.user_id == user_id
        )
    )
    if row is None:
        raise ValueError("Session reference index ownership is unavailable.")
    await invalidate(db, row)
    db.info["world_info_changed"] = True
