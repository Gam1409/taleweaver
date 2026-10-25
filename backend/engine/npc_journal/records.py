"""Journal storage, deduplication and bounded memory for future LLM turns."""

import hashlib
import unicodedata
from copy import deepcopy
from typing import Any

from backend.engine.npc_journal.schema import CharacterObservation

JOURNAL_KEY = "npc_journal"
_PHYSICAL_CATEGORIES = {"appearance", "equipment", "belongings"}


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def supported_quote(quote: str | None, narration: str) -> bool:
    return bool(quote and len(quote.strip()) >= 3 and normalized(quote) in normalized(narration))


def journal_of(npc: Any) -> dict:
    meta = getattr(npc, "metadata_json", None) or {}
    value = meta.get(JOURNAL_KEY)
    return deepcopy(value) if isinstance(value, dict) else {}


def append_observations(npc: Any, extraction: CharacterObservation, message: Any) -> None:
    journal = journal_of(npc)
    entries = list(journal.get("entries") or [])
    existing = {entry.get("id") for entry in entries}
    for observation in extraction.observations:
        if not supported_quote(observation.evidence, message.content):
            continue
        key = "|".join([str(message.id), observation.category, normalized(observation.text)])
        entry_id = hashlib.sha256(key.encode()).hexdigest()[:32]
        if entry_id in existing:
            continue
        entries.append(
            {
                "id": entry_id,
                "message_id": message.id,
                "scene_id": message.scene_id,
                "recorded_at": message.created_at.isoformat(),
                **observation.model_dump(exclude_none=True),
            }
        )
        existing.add(entry_id)
    aliases = list(journal.get("aliases") or [])
    sources = dict(journal.get("alias_sources") or {})
    for alias in extraction.aliases:
        if len(alias) <= 100 and supported_quote(alias, message.content) and alias not in aliases:
            aliases.append(alias)
            sources[alias] = message.id
    entries.sort(key=lambda e: (e.get("recorded_at", ""), e.get("message_id", "")))
    journal.update(version=1, entries=entries, aliases=aliases[:20], alias_sources=sources)
    npc.metadata_json = {**(npc.metadata_json or {}), JOURNAL_KEY: journal}


def memory_context(npc: Any, limit: int = 1600, *, visual_only: bool = False) -> str:
    """Keep the full journal in storage, but cap material repeated in model prompts."""
    journal = journal_of(npc)
    latest: dict[str, dict] = {}
    for entry in journal.get("entries") or []:
        if visual_only and entry.get("source") != "observed":
            continue
        category = entry.get("category", "event")
        if visual_only and category not in _PHYSICAL_CATEGORIES:
            continue
        # A cloak remains the same topic when it is worn, stored, given away or lost.
        subject = entry.get("topic", "general")
        group = (
            "physical" if category in _PHYSICAL_CATEGORIES and subject != "general" else category
        )
        topic = f"{group}/{subject}"
        latest.pop(topic, None)
        latest[topic] = entry
    facts = [
        f"{category} ({e.get('source', 'observed')}): {e.get('text', '')}"
        for category, e in reversed(list(latest.items()))
    ]
    prefix = " Last learned information (may be outdated; live state takes precedence): "
    if visual_only:
        prefix = (
            " Last observed physical information (overrides older appearance; depict only "
            "explicitly visible/worn items, never stored, given-away, dropped or consumed items): "
        )
    return (prefix + "; ".join(facts))[:limit] if facts else ""
