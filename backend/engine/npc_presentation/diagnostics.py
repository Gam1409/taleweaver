"""Content-free diagnostics for the metadata attached to the committed narrator reply."""

import logging
from typing import TYPE_CHECKING, Any

from backend.core.state_rejection_trace import reject
from backend.core.system_diagnostics import service

if TYPE_CHECKING:
    from backend.engine.npc_presentation.runtime import PresentationTurn

logger = logging.getLogger(__name__)


def report(manager: Any, turn: "PresentationTurn", text: str, *, completed: bool) -> None:
    payload = turn.payload(text) if completed else None
    reason = turn.diagnostic(text, completed=completed)
    if reason in {
        "missing_footer",
        "incomplete_footer",
        "footer_too_large",
        "source_mismatch",
        "incomplete_narration",
    }:
        reject(
            "emotion",
            f"presentation.{reason}",
            "Requested NPC presentation could not be confirmed for the final narration.",
            narration=text,
            completed=completed,
            catalog=turn.catalog,
            proposals=turn.candidates,
            metadata=turn.stream.footer,
            preferences=turn.preferences,
        )
    session_id = getattr(manager.state, "session_id", None)
    cues = payload["npcs"].values() if payload else ()
    fields = {
        "session_id": session_id,
        "turn_id": getattr(manager, "turn_id", None),
        "phase": "narration",
        "presentation_reason": reason,
        "candidates": len(turn.catalog),
        "selected_count": len(payload["npcs"]) if payload else 0,
        "emotion_count": sum(
            cue.get("emotion") not in (None, "unknown") and cue.get("intensity") is not None
            for cue in cues
        ),
        "thought_count": sum(bool(cue.get("thought")) for cue in cues),
    }
    service.emit("npc.presentation", **fields)
    if turn.preferences.enabled:
        logger.info(
            "NPC presentation: session=%s reason=%s cast=%d assessed=%d emotions=%d thoughts=%d",
            session_id,
            reason,
            fields["candidates"],
            fields["selected_count"],
            fields["emotion_count"],
            fields["thought_count"],
        )
