"""Commit reviewed expressions and their provenance, never physical world effects."""

from typing import Any

from backend.core.state_rejection_trace import reject
from backend.engine.chpm import memory
from backend.engine.chpm.kernel import ChpmError, digest
from backend.engine.chpm.schema import Decision, MemoryEntry, Perception


def finish_decision(turn: Any, decision: Decision, reply: Any) -> None:
    if turn.initial.settings.mode == "shadow":
        decision.status = "shadow"
        return
    if turn.verdict is None or not turn.verdict.matches:
        reject(
            "emotion",
            "chpm.commit_unconfirmed",
            "CHPM cannot commit a reply without successful validation.",
            decisions=turn.decisions,
            verdict=turn.verdict,
            confirmed_state=turn.initial,
        )
        raise ChpmError("CHPM cannot commit a reply without successful validation.")
    decision.status = "delivered"
    decision.reply_id = reply.id
    decision.reply_revision = reply.revision_id
    decision.reply_hash = digest(reply.content)
    decision.spoken_evidence = next(
        (entry.quote for entry in turn.verdict.evidence if entry.actor_id == decision.actor_id), ""
    )
    decision.action_evidence = next(
        (entry.quote for entry in turn.verdict.actions if entry.actor_id == decision.actor_id), ""
    )
    decision.action_evidence_span = next(
        (
            entry.evidence_span
            for entry in turn.verdict.actions
            if entry.actor_id == decision.actor_id
        ),
        None,
    )


def new_memories(turn: Any, decision: Decision, reply: Any) -> list[MemoryEntry]:
    actor = decision.actor_id
    source = decision.observation
    perceived = turn.perceptions.get(actor, Perception(actor_id=actor))
    additions = [
        MemoryEntry(
            source_message_id=source.message_id,
            source_revision_id=source.revision_id,
            source_hash=source.content_hash,
            source_role="user",
            scene_id=source.source_scene_id or source.scene_id,
            observer_id=actor,
            speaker_id="@player",
            kind="player_observation",
            quote=quote,
        )
        for quote in perceived.quotes
    ]
    if turn.verdict is None:
        return additions
    for kind, quote in (
        ("own_speech", decision.spoken_evidence),
        ("own_action", decision.action_evidence),
    ):
        if quote:
            entry = memory.from_source(reply, actor, actor, quote, kind)
            if kind == "own_action":
                entry.action_span = decision.action_evidence_span
            additions.append(entry)
    additions.extend(
        memory.from_source(reply, actor, heard.speaker_id, heard.quote, "heard_speech")
        for heard in turn.verdict.heard
        if heard.actor_id == actor
    )
    return additions
