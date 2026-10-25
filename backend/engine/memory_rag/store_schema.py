"""Lance schema and filter helpers. No untrusted value becomes an identifier."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Scope:
    user_id: str
    session_id: str
    epoch: int
    signature: str


def literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def scope_filter(scope: Scope) -> str:
    if type(scope.epoch) is not int or scope.epoch < 0:
        raise ValueError("Memory epoch must be a nonnegative integer.")
    return " AND ".join(
        [
            f"user_id = {literal(scope.user_id)}",
            f"session_id = {literal(scope.session_id)}",
            f"epoch = {scope.epoch}",
            f"signature = {literal(scope.signature)}",
        ]
    )


def table_name(signature: str) -> str:
    return "memory_" + hashlib.sha256(signature.encode()).hexdigest()


def schema(dimension: int) -> Any:
    import pyarrow as pa

    strings = [
        "id",
        "user_id",
        "session_id",
        "template_id",
        "signature",
        "layer",
        "source_id",
        "source_hash",
        "npc_id",
        "scene_id",
        "text",
        "provenance",
        "source_message_ids",
        "created_at",
    ]
    return pa.schema(
        [(name, pa.string()) for name in strings]
        + [("epoch", pa.int64()), ("vector", pa.list_(pa.float32(), dimension))]
    )


def row(scope: Scope, document: dict, vector: list[float]) -> dict:
    result = {
        name: str(document.get(name) or "")
        for name in [
            "id",
            "template_id",
            "layer",
            "source_id",
            "source_hash",
            "npc_id",
            "scene_id",
            "text",
            "provenance",
        ]
    }
    if not all(result[name] for name in ("id", "layer", "source_id", "source_hash", "text")):
        raise ValueError("Memory document is missing required metadata.")
    for field in ("user_id", "session_id"):
        if document.get(field) is not None and str(document[field]) != getattr(scope, field):
            raise ValueError("Memory document ownership differs from its scope.")
    message_ids = document.get("source_message_ids") or []
    result.update(
        user_id=scope.user_id,
        session_id=scope.session_id,
        epoch=scope.epoch,
        signature=scope.signature,
        vector=vector,
        source_message_ids=json.dumps(message_ids),
        created_at=str(document.get("created_at") or datetime.now(timezone.utc).isoformat()),
    )
    return result


def query_filter(
    scope: Scope, layers: list[str] | None, npc_ids: list[str] | None, scene_id: str | None
) -> str:
    filters = [scope_filter(scope)]
    if layers is not None:
        filters.append(_membership("layer", layers))
    if npc_ids is not None:
        filters.append(_membership("npc_id", npc_ids))
    if scene_id is not None:
        filters.append(f"scene_id = {literal(scene_id)}")
    return " AND ".join(filters)


def _membership(field: str, values: list[str]) -> str:
    if not values:
        return "false"
    return field + " IN (" + ",".join(literal(value) for value in values) + ")"


def lexical_filter(text: str) -> str:
    terms = sorted(set(re.findall(r"\w{2,}", text.lower())))[:24]
    if not terms:
        return "false"
    return "(" + " OR ".join("contains(lower(text), " + literal(term) + ")" for term in terms) + ")"


def hybrid_rank(
    vector_rows: list[dict], lexical_rows: list[dict], text: str, limit: int
) -> list[dict]:
    terms = set(re.findall(r"\w{2,}", text.lower()))
    lexical_rows.sort(
        key=lambda item: len(terms & set(re.findall(r"\w{2,}", item["text"].lower()))), reverse=True
    )
    scores: dict[str, float] = {}
    rows: dict[str, dict] = {}
    for candidates in (vector_rows, lexical_rows):
        for rank, candidate in enumerate(candidates, start=1):
            key = candidate["id"]
            scores[key] = scores.get(key, 0) + 1 / (60 + rank)
            rows[key] = candidate
    result = []
    for key in sorted(scores, key=lambda key: (-scores[key], key))[:limit]:
        candidate = {
            field: value
            for field, value in rows[key].items()
            if field not in {"vector", "_distance"}
        }
        candidate["score"] = scores[key]
        candidate["source_message_ids"] = json.loads(candidate["source_message_ids"])
        result.append(candidate)
    return result
