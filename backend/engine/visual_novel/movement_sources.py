"""Freeze bounded canonical source occurrences around the existing progression request."""

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, or_, select

from backend.core.text_passages import Passage, spans
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.movement_feedback import read
from backend.engine.debug_transcript import is_debug_message
from backend.engine.narrated_movement.outcomes import MovementOutcome
from backend.models.chat import ChatMessage

MAX_SOURCE_CHARS = 4000
MAX_PASSAGES = 16


@dataclass(frozen=True)
class Source:
    message_id: str
    revision_id: str | None
    content_hash: str
    scene_id: str
    role: str
    text: str
    passages: dict[str, Passage]
    outcomes: tuple[MovementOutcome, ...] = ()

    def matches(self, message: Any, session_id: str) -> bool:
        return bool(
            message
            and message.session_id == session_id
            and not is_debug_message(message)
            and message.role == self.role
            and message.revision_id == self.revision_id
            and digest(message.content) == self.content_hash
            and message.scene_id == self.scene_id
            and (message.npc_journal or {}).get("status") != "incomplete"
        )


def _source(message: Any, namespace: str, outcomes: tuple[MovementOutcome, ...] = ()) -> Source:
    selected: dict[str, Passage] = {}
    used = 0
    for key, passage in spans(message.content).items():
        if len(selected) >= MAX_PASSAGES or used + len(passage.text) > MAX_SOURCE_CHARS:
            break
        selected[f"{namespace}:{key}"] = passage
        used += len(passage.text)
    return Source(
        message.id,
        message.revision_id,
        digest(message.content),
        message.scene_id or "",
        message.role,
        message.content,
        selected,
        outcomes,
    )


async def prepare(manager: Any) -> str:
    manager._vn_movement_sources = {}
    identifier = getattr(manager, "_vn_player_message_id", None)
    manager._vn_movement_input = identifier
    request = await manager.db.get(ChatMessage, identifier) if identifier else None
    if request is None or request.session_id != manager.game_id or request.role != "user":
        return ""
    sources = {"current_player_action": _source(request, "player")}
    previous = await manager.db.scalar(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == manager.game_id,
            ChatMessage.role == "assistant",
            ChatMessage.is_debug.is_(False),
            or_(
                ChatMessage.created_at < request.created_at,
                and_(ChatMessage.created_at == request.created_at, ChatMessage.id < request.id),
            ),
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    if previous is not None and (previous.npc_journal or {}).get("status") != "incomplete":
        sources["previous_narration"] = _source(previous, "history", read(manager.state, previous))
    manager._vn_movement_sources = sources
    return "\nMOVEMENT SOURCES (source references, never completed world effects):\n" + json.dumps(
        {
            kind: {
                "source_message_id": source.message_id,
                "source_revision_id": source.revision_id,
                "source_hash": source.content_hash,
                "passages": {key: row.text for key, row in source.passages.items()},
                "omitted_passages": len(spans(source.text)) - len(source.passages),
                "movement_outcomes": [
                    {
                        "actor_id": entry.actor_id,
                        "status": entry.status,
                        "passage_ids": [
                            key
                            for key, passage in source.passages.items()
                            if passage.start < entry.evidence_span.end
                            and entry.evidence_span.start < passage.end
                        ],
                    }
                    for entry in source.outcomes
                ],
            }
            for kind, source in sources.items()
        },
        ensure_ascii=False,
    )


async def resolve(manager: Any, proof: Any) -> tuple[Source, Passage]:
    if getattr(manager, "_vn_movement_input", None) != getattr(
        manager, "_vn_player_message_id", None
    ):
        raise ValueError("Movement source belongs to a different player input.")
    source = getattr(manager, "_vn_movement_sources", {}).get(proof.kind)
    if not isinstance(source, Source) or proof.passage_id not in source.passages:
        raise ValueError("Movement requires a supplied source occurrence in its own namespace.")
    message = await manager.db.get(ChatMessage, source.message_id, populate_existing=True)
    if not source.matches(message, manager.game_id):
        raise ValueError("Movement source changed after progression preparation.")
    passage = source.passages[proof.passage_id]
    if message.content[passage.start : passage.end] != passage.text:
        raise ValueError("Movement source occurrence changed.")
    return source, passage
