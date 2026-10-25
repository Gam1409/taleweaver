"""Keep character knowledge aligned with imported, copied and rewound conversations."""

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.npc_journal.records import JOURNAL_KEY, journal_of
from backend.models.world_entity import WorldEntity


def remap_journal(metadata: dict | None, message_ids: dict[str, str]) -> dict:
    result = deepcopy(metadata or {})
    journal = result.get(JOURNAL_KEY)
    if not isinstance(journal, dict):
        return result
    original = journal.get("introduced_message_id")
    if original:
        journal["introduced_message_id"] = message_ids.get(original, original)
    for entry in journal.get("entries") or []:
        original = entry.get("message_id")
        entry["message_id"] = message_ids.get(original, original)
    journal["alias_sources"] = {
        alias: message_ids.get(source, source)
        for alias, source in (journal.get("alias_sources") or {}).items()
    }
    # Running image jobs belong to the old session/process, never the copy.
    if journal.get("portrait_status") == "running":
        journal["portrait_status"] = "interrupted"
    return result


async def rewind_journals(
    db: AsyncSession, session_id: str, removed_message_ids: list[str]
) -> None:
    removed = set(removed_message_ids)
    npcs = (
        await db.scalars(
            select(WorldEntity).where(
                WorldEntity.session_id == session_id,
                WorldEntity.entity_type == "NPC",
            )
        )
    ).all()
    for npc in npcs:
        await _rewind_npc(db, npc, removed)


async def _rewind_npc(db: AsyncSession, npc: WorldEntity, removed: set[str]) -> None:
    journal = journal_of(npc)
    if not journal:
        return
    if journal.get("origin") == "introduced" and journal.get("introduced_message_id") in removed:
        await db.delete(npc)
        return
    journal["entries"] = [
        e for e in journal.get("entries") or [] if e.get("message_id") not in removed
    ]
    sources = journal.get("alias_sources") or {}
    journal["aliases"] = [a for a in journal.get("aliases") or [] if sources.get(a) not in removed]
    journal["alias_sources"] = {a: s for a, s in sources.items() if s not in removed}
    if journal.get("origin") == "introduced":
        appearances = [
            e["text"]
            for e in journal["entries"]
            if e.get("category") == "appearance" and e.get("source") == "observed"
        ]
        npc.description = appearances[0][:1000] if appearances else ""
    npc.metadata_json = {**npc.metadata_json, JOURNAL_KEY: journal}
