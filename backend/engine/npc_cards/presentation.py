"""Deterministic public journal summaries and explicitly enabled social estimates."""

from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.npc_cards.settings import card_insights_enabled
from backend.engine.npc_journal.records import normalized, supported_quote
from backend.engine.visual_novel.presentation import session_is_vn
from backend.engine.visual_novel.state import load_state
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState

HistoryKind = Literal["all", "general", "shared"]

SUMMARY_FIELDS = {
    "id",
    "message_id",
    "scene_id",
    "recorded_at",
    "category",
    "topic",
    "text",
    "evidence",
    "source",
    "player_attitude",
}


def public_entries(entries: list[dict]) -> list[dict]:
    """Imported metadata cannot add private implementation fields to journal responses."""
    return [
        {key: value for key, value in entry.items() if key in SUMMARY_FIELDS}
        for entry in entries
        if isinstance(entry, dict)
    ]


def history_section(entry: dict) -> Literal["general", "shared"]:
    if entry.get("category") == "event" or (
        entry.get("category") == "relationship" and entry.get("topic") == "relationship_player"
    ):
        return "shared"
    return "general"


def history_page(entries: list[dict], kind: HistoryKind, offset: int) -> dict:
    """Filter before paginating; each observation belongs to exactly one history tab."""
    counts = {"general": 0, "shared": 0}
    selected = []
    for entry in entries:
        section = history_section(entry)
        counts[section] += 1
        if kind in ("all", section):
            selected.append(entry)
    return {
        "history_kind": kind,
        "history_counts": counts,
        "entries": selected[offset : offset + 50],
        "has_more": len(selected) > offset + 50,
    }


def recent_summary(entries: list[dict]) -> list[dict]:
    """Summarize shared events only, without inventing feelings or translating known facts."""
    candidates = [
        entry for entry in entries if isinstance(entry, dict) and history_section(entry) == "shared"
    ]
    return _latest_facts(candidates, limit=4)


def character_overview(entries: list[dict]) -> list[dict]:
    """A compact biography from learned background facts, preserving unverified claims."""
    candidates = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("category") == "background"
    ]
    return _latest_facts(candidates, limit=3)


def _latest_facts(entries: list[dict], *, limit: int) -> list[dict]:
    candidates = sorted(
        entries,
        key=lambda entry: (str(entry.get("recorded_at") or ""), str(entry.get("message_id") or "")),
        reverse=True,
    )
    topics: set[tuple[str, str]] = set()
    texts: set[str] = set()
    selected = []
    for entry in candidates:
        if not _fact_candidate(entry):
            continue
        text = normalized(entry["text"])
        topic = normalized(str(entry.get("topic") or "general"))
        key = (entry["category"], text if topic == "general" else topic)
        if key in topics or text in texts:
            continue
        topics.add(key)
        texts.add(text)
        selected.append({key: value for key, value in entry.items() if key in SUMMARY_FIELDS})
        if len(selected) == limit:
            break
    return selected


def _fact_candidate(entry: dict) -> bool:
    return (
        entry.get("source") in ("observed", "claimed")
        and isinstance(entry.get("text"), str)
        and bool(entry["text"].strip())
        and isinstance(entry.get("evidence"), str)
        and bool(entry["evidence"].strip())
    )


def _unavailable() -> dict[str, Any]:
    return {
        "available": False,
        "relationship": None,
        "emotion": None,
        "evidence": None,
        "source_message_id": None,
    }


async def character_insights(db: AsyncSession, state: SessionState, npc_id: str) -> dict | None:
    """Opt-in estimates require completed assistant evidence, never a blank default profile."""
    if not card_insights_enabled(state):
        return None
    if not await session_is_vn(db, state):
        return _unavailable()
    social = load_state(state)
    character = social.characters.get(npc_id) if social else None
    if character is None:
        return _unavailable()
    source_ids = set(social.reviewed_scene_message_ids)
    source_ids.update(memory.source_message_id for memory in character.memories)
    if not source_ids:
        return _unavailable()
    messages = (
        await db.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == state.session_id,
                ChatMessage.role == "assistant",
                ChatMessage.id.in_(source_ids),
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        )
    ).all()
    sources = {message.id: message.content or "" for message in messages}
    memory = next(
        (
            memory
            for memory in reversed(character.memories)
            if supported_quote(memory.evidence, sources.get(memory.source_message_id, ""))
        ),
        None,
    )
    emotion_message = next(
        (
            message
            for message in messages
            if supported_quote(character.emotion_cause, message.content or "")
        ),
        None,
    )
    if memory is None and emotion_message is None:
        return _unavailable()
    return {
        "available": True,
        "relationship": character.relationship.model_dump() if memory else None,
        "emotion": character.emotion if emotion_message else None,
        "evidence": character.emotion_cause if emotion_message else memory.evidence,
        "source_message_id": emotion_message.id if emotion_message else memory.source_message_id,
    }
