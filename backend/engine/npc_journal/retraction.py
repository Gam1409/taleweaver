"""Retract knowledge attributed to a replaced reply without undoing game mechanics."""

from typing import Any

from backend.engine.npc_journal.records import JOURNAL_KEY, journal_of


def retract_reply(npc: Any, message_id: str) -> None:
    journal = journal_of(npc)
    if not journal:
        return
    entries = journal.get("entries") or []
    removed = [entry for entry in entries if entry.get("message_id") == message_id]
    journal["entries"] = [entry for entry in entries if entry.get("message_id") != message_id]
    sources = journal.get("alias_sources") or {}
    journal["aliases"] = [
        alias for alias in journal.get("aliases", []) if sources.get(alias) != message_id
    ]
    journal["alias_sources"] = {
        alias: source for alias, source in sources.items() if source != message_id
    }
    if journal.get("introduced_message_id") == message_id:
        journal.pop("introduction", None)
    _retract_description(npc, journal, removed, message_id)
    if journal != journal_of(npc):
        npc.metadata_json = {**(npc.metadata_json or {}), JOURNAL_KEY: journal}


def _retract_description(npc: Any, journal: dict, removed: list[dict], message_id: str) -> None:
    if journal.get("origin") != "introduced":
        return
    source = journal.get("description_source")
    observed = journal.get("observed_description")
    # Older records did not record a description source. Only retract an exact
    # match to removed observed appearance, never an authored/manual description.
    legacy = " ".join(
        entry.get("text", "")
        for entry in removed
        if entry.get("category") == "appearance" and entry.get("source") == "observed"
    )[:1000]
    matches = source == message_id and npc.description == observed
    matches_legacy = source is None and bool(legacy) and npc.description == legacy
    if matches or matches_legacy:
        npc.description = ""
    if source == message_id:
        journal.pop("description_source", None)
        journal.pop("observed_description", None)
