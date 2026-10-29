"""Journal storage, deduplication and bounded memory for future LLM turns."""

import hashlib
import unicodedata
from copy import deepcopy
from typing import Any, get_args

from backend.engine.npc_journal.schema import CharacterObservation, Observation, Significance

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


def is_significant(observation: Observation) -> bool:
    """Validate the model's semantic classification without another model call.

    Legacy payloads without these fields remain accepted. This is not a semantic
    classifier: a model that falsely labels a gesture durable can still be wrong.
    """
    if observation.significance == "ephemeral" or observation.effect == "none":
        return False
    if observation.significance is None:
        return True
    return observation.effect is not None and bool(observation.reason)


def _record(observation: Observation) -> dict:
    record = observation.model_dump(exclude_none=True)
    if record["topic"] == "general" and observation.significance:
        record["topic"] = observation.significance
    return record


def _fact_key(entry: dict) -> tuple[str, str, str]:
    return (
        str(entry.get("category", "event")),
        normalized(str(entry.get("topic", "general"))),
        str(entry.get("source", "observed")),
    )


def _repeats_known_fact(entries: list[dict], record: dict, message_id: str) -> bool:
    matching = [entry for entry in entries if _fact_key(entry) == _fact_key(record)]
    if not matching:
        return False
    if any(
        entry.get("message_id") == message_id
        and normalized(entry.get("text", "")) == normalized(record["text"])
        for entry in matching
    ):
        return True
    # A -> B -> A is a meaningful reversal for a specific topic. Legacy "general"
    # mixes unrelated facts, so an intervening unrelated entry is not a reversal.
    broad_topic = record["topic"] in ("general", *get_args(Significance))
    candidates = matching if broad_topic else matching[-1:]
    return any(
        normalized(entry.get("text", "")) == normalized(record["text"]) for entry in candidates
    )


def append_observations(npc: Any, extraction: CharacterObservation, message: Any) -> None:
    journal = journal_of(npc)
    entries = list(journal.get("entries") or [])
    existing = {entry.get("id") for entry in entries}
    for observation in extraction.observations:
        if not is_significant(observation) or not supported_quote(
            observation.evidence, message.content
        ):
            continue
        record = _record(observation)
        key = "|".join([str(message.id), *_fact_key(record), normalized(observation.text)])
        entry_id = hashlib.sha256(key.encode()).hexdigest()[:32]
        if entry_id in existing or _repeats_known_fact(entries, record, message.id):
            continue
        entries.append(
            {
                "id": entry_id,
                "message_id": message.id,
                "scene_id": message.scene_id,
                "recorded_at": message.created_at.isoformat(),
                **record,
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


def fact_topic(entry: dict) -> str:
    """Broad legacy labels are not identities: preserve their distinct facts."""
    topic = str(entry.get("topic") or "general")
    if topic == "general" or topic in get_args(Significance):
        return (
            "fact_"
            + hashlib.sha256(normalized(str(entry.get("text", ""))).encode()).hexdigest()[:16]
        )
    return topic


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
        topic = f"{group}/{fact_topic(entry)}"
        latest.pop(topic, None)
        latest[topic] = entry
    facts = [
        f"{e.get('category', 'event')} ({e.get('source', 'observed')}): {e.get('text', '')}"
        for e in reversed(list(latest.values()))
    ]
    prefix = " Last learned information (may be outdated; live state takes precedence): "
    if visual_only:
        prefix = (
            " Last observed physical information (overrides older appearance; depict only "
            "explicitly visible/worn items, never stored, given-away, dropped or consumed items): "
        )
    return (prefix + "; ".join(facts))[:limit] if facts else ""
