"""Lazy journal access; compressed canonical blocks stay portable and unchanged."""

import hashlib
import json
from collections.abc import Iterator
from copy import deepcopy
from typing import Any

from backend.engine.npc_journal.archive import decode


def raw(npc: Any) -> dict:
    journal = (getattr(npc, "metadata_json", None) or {}).get("npc_journal")
    return journal if isinstance(journal, dict) else {}


def describe(chunk: str, records: list[dict]) -> dict:
    # Last occurrence order matters when one reply established several facts.
    ids = list(
        dict.fromkeys(row.get("message_id") for row in reversed(records) if row.get("message_id"))
    )
    values = {"chunk_hash": hashlib.sha256(chunk.encode()).hexdigest(), "messages": ids[::-1]}
    return {**values, "index_hash": _index_hash(values)}


def _index_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def hints(journal: dict, index: int, chunk: str) -> list[str] | None:
    values = journal.get("archive_index")
    value = values[index] if isinstance(values, list) and index < len(values) else None
    if (
        not isinstance(chunk, str)
        or not isinstance(value, dict)
        or value.get("chunk_hash") != hashlib.sha256(chunk.encode()).hexdigest()
    ):
        return None
    messages = value.get("messages")
    if (
        not isinstance(messages, list)
        or len(messages) > 128
        or not all(isinstance(key, str) for key in messages)
    ):
        return None
    if value.get("index_hash") != _index_hash(
        {"chunk_hash": value["chunk_hash"], "messages": messages}
    ):
        return None
    return messages


def index_for(journal: dict, index: int, chunk: str) -> dict:
    if hints(journal, index, chunk) is not None:
        return dict(journal["archive_index"][index])
    return describe(chunk, decode(chunk))


def entries(
    npc: Any, *, reverse: bool = False, message_ids: set[str] | None = None
) -> Iterator[dict]:
    journal = raw(npc)
    if message_ids is not None and not message_ids:
        return
    tail = journal.get("entries") or []
    chunks = list(enumerate(journal.get("archive") or []))
    if reverse:
        yield from _selected(reversed(tail), message_ids)
        chunks.reverse()
    for index, chunk in chunks:
        known = hints(journal, index, chunk) if message_ids is not None else None
        if known is not None and message_ids is not None and message_ids.isdisjoint(known):
            continue
        records = decode(chunk)
        yield from _selected(reversed(records) if reverse else records, message_ids)
    if not reverse:
        yield from _selected(tail, message_ids)


def _selected(rows: Any, message_ids: set[str] | None) -> Iterator[dict]:
    for row in rows:
        if message_ids is None or row.get("message_id") in message_ids:
            yield deepcopy(row)


def source_ids(npc: Any) -> Iterator[str]:
    journal = raw(npc)
    for row in reversed(journal.get("entries") or []):
        if row.get("message_id"):
            yield row["message_id"]
    for index in reversed(range(len(journal.get("archive") or []))):
        chunk = journal["archive"][index]
        known = hints(journal, index, chunk)
        if known is not None:
            yield from reversed(known)
            continue
        for row in reversed(decode(chunk)):
            if row.get("message_id"):
                yield row["message_id"]
