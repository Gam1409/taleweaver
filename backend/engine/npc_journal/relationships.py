"""Last learned attitude toward the player, derived only from evidenced journal entries."""

from typing import Any, get_args

from backend.engine.npc_journal.schema import PlayerAttitude

_ATTITUDES = frozenset(get_args(PlayerAttitude))


def player_relationship(journal: dict[str, Any]) -> dict[str, Any]:
    """Do not infer neutrality or parse arbitrary-language prose into a relationship score."""
    for entry in reversed(journal.get("entries") or []):
        if (
            not isinstance(entry, dict)
            or entry.get("category") != "relationship"
            or entry.get("topic") != "relationship_player"
        ):
            continue
        value = entry.get("player_attitude")
        status = value if isinstance(value, str) and value in _ATTITUDES else "unknown"
        return {
            "status": status,
            "source": entry.get("source"),
            "text": entry.get("text"),
            "evidence": entry.get("evidence"),
            "recorded_at": entry.get("recorded_at"),
        }
    return {
        "status": "unknown",
        "source": None,
        "text": None,
        "evidence": None,
        "recorded_at": None,
    }
