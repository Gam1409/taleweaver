"""One escaped JSON quota for processing, review edits and portable entry rows."""

import json
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.world_info import limits
from backend.models.world_info import WorldInfoEntry

# Ownership and timestamps are bounded routing metadata outside the entry quota.
_FIELDS = (
    "id",
    "source_id",
    "source_revision_id",
    "batch_index",
    "ordinal",
    "title",
    "summary",
    "group_name",
    "facts",
    "tags",
    "relations",
    "kind",
    "audience",
    "known_by",
    "unresolved_known_by",
    "status",
    "version",
    "search_text",
    "content_hash",
    "edited",
)
_DEFAULTS: dict[str, Any] = {
    "summary": "",
    "group_name": "",
    "tags": [],
    "relations": [],
    "kind": "background_lore",
    "audience": "narrator_only",
    "known_by": [],
    "unresolved_known_by": [],
    "status": "draft",
    "version": 1,
    "edited": False,
}


class CapacityError(ValueError):
    """A proposed canonical corpus exceeds a shared persistence/portability bound."""


def _payload(row: Any) -> dict[str, Any]:
    values = {}
    for key in _FIELDS:
        value = row.get(key) if isinstance(row, Mapping) else getattr(row, key, None)
        if value is None:
            value = _DEFAULTS.get(key)
        if value is None:
            raise CapacityError("Knowledge entry metadata is incomplete.")
        values[key] = value
    # Missing characters acquire a dormant marker during export. Reserve that
    # bounded growth now without granting knowledge or changing the actual ACL.
    values["unresolved_known_by"] = sorted(
        set(values["unresolved_known_by"]) | set(values["known_by"])
    )
    return values


def _json_model(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise CapacityError("Knowledge entry metadata cannot be serialized.")


def entry_bytes(row: Any) -> int:
    """Match portable content before/after defaults, flush and ownership remapping."""
    return len(
        json.dumps(
            _payload(row),
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
            default=_json_model,
        ).encode("utf-8")
    )


def corpus_entry_bytes(rows: Iterable[Any]) -> int:
    """Include JSON array framing and separators, with no text truncation."""
    sizes = [entry_bytes(row) for row in rows]
    return 2 + sum(sizes) + max(0, len(sizes) - 1)


def validate_entry_capacity(rows: Iterable[Any]) -> None:
    entries = list(rows)
    if (
        len(entries) > limits.MAX_SESSION_ENTRIES
        or sum(len(_payload(row)["facts"]) for row in entries) > limits.MAX_SESSION_FACTS
        or corpus_entry_bytes(entries) > limits.MAX_SESSION_ENTRY_BYTES
    ):
        raise CapacityError("Session knowledge exceeds its entry storage budget.")


async def ensure_entry_capacity(
    db: AsyncSession,
    user_id: str,
    session_id: str,
    proposed_rows: Iterable[Any],
    *,
    replace_ids: Iterable[str] = (),
) -> None:
    """Call in the fenced mutation transaction before replacing prior accepted data."""
    rows = list(
        await db.scalars(
            select(WorldInfoEntry)
            .where(
                WorldInfoEntry.user_id == user_id,
                WorldInfoEntry.session_id == session_id,
                WorldInfoEntry.id.not_in(set(replace_ids)),
            )
            .limit(limits.MAX_SESSION_ENTRIES + 1)
            .execution_options(populate_existing=True)
        )
    )
    validate_entry_capacity([*rows, *proposed_rows])
