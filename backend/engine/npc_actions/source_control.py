"""Remember source-time command ownership on the existing canonical reply envelope."""

from dataclasses import dataclass
from typing import Any

from backend.engine import turn_controls
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.recovery_contracts import RecoveryAudit
from backend.engine.debug_transcript import is_debug_message
from backend.engine.npc_actions.control import validated_outcomes

FIELD = "command_controlled_actor_ids"


@dataclass(frozen=True)
class Snapshot:
    actor_ids: frozenset[str] = frozenset()
    signature: str = "legacy"
    valid: bool = True


def read(message: Any) -> Snapshot:
    raw = getattr(message, "npc_recovery", None)
    if not isinstance(raw, dict) or raw.get(FIELD) is None:
        return Snapshot()
    # Freeze only authority-bearing fields; independent catch-up cursor advances
    # do not change this source's command ownership.
    signature = turn_controls.fingerprint(
        {key: raw.get(key) for key in (FIELD, "content_hash", "revision_id", "scene_id")}
    )
    if (
        message.role != "assistant"
        or is_debug_message(message)
        or (getattr(message, "npc_journal", None) or {}).get("status") == "incomplete"
    ):
        return Snapshot(signature=signature, valid=False)
    try:
        audit = RecoveryAudit.model_validate(raw)
    except ValueError:
        return Snapshot(signature=signature, valid=False)
    if (audit.content_hash, audit.revision_id, audit.scene_id) != (
        digest(message.content),
        message.revision_id,
        message.scene_id or "",
    ):
        return Snapshot(signature=signature, valid=False)
    return Snapshot(frozenset(audit.command_controlled_actor_ids or ()), signature)


def stamp(manager: Any, turn: Any, reply: Any) -> None:
    """An explicit approved empty plan is control; settings alone never are."""
    outcomes = validated_outcomes(turn)
    if not outcomes:
        return
    if (
        reply.session_id != manager.game_id
        or reply.role != "assistant"
        or is_debug_message(reply)
        or (getattr(reply, "npc_journal", None) or {}).get("status") == "incomplete"
    ):
        raise ValueError("Command source ownership requires this session's completed reply.")
    raw = getattr(reply, "npc_recovery", None)
    audit = (
        RecoveryAudit.model_validate(raw)
        if raw is not None
        else RecoveryAudit(
            content_hash=digest(reply.content),
            revision_id=reply.revision_id,
            scene_id=reply.scene_id or "",
            game_minute=max(0, int(getattr(manager.state, "in_game_time", 0) or 0)),
            actors={},
        )
    )
    if (audit.content_hash, audit.revision_id, audit.scene_id) != (
        digest(reply.content),
        reply.revision_id,
        reply.scene_id or "",
    ):
        raise ValueError("The command source envelope changed before completion.")
    audit.command_controlled_actor_ids = sorted(outcomes)
    # Revalidate the existing actor bound rather than silently truncating control.
    reply.npc_recovery = RecoveryAudit.model_validate(audit.model_dump()).model_dump()
