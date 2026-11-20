"""Read-only movement authorization projection; psychological content stays private."""

from typing import Any, Literal

from backend.core.text_evidence import EvidenceSpan, unique_span
from backend.engine.chpm.recovery_contracts import RecoveryAudit
from backend.engine.chpm.state import controls, load


def historical_action(
    state: Any, actor_id: str, message: Any, span: EvidenceSpan
) -> Literal["reviewed", "fallback", "blocked", "unowned"]:
    """Bind recovery to this actor's reviewed expression, never to arbitrary old prose."""
    from backend.engine.chpm.kernel import digest

    if not controls(state, actor_id):
        return _fallback(None, actor_id, message, span)
    kernel = load(state)
    fallback = _fallback(kernel, actor_id, message, span)
    if fallback == "blocked":
        return fallback
    mind = kernel.minds.get(actor_id)
    if mind is None or (
        mind.genesis.scope.world_id != message.session_id
        or mind.genesis.scope.observer_id != actor_id
    ):
        return fallback
    matched = []
    bindings = []
    for source in mind.sources.values():
        if (
            source.message_id != message.id
            or source.revision_id != message.revision_id
            or source.content_hash != digest(message.content)
            or source.role != "assistant"
        ):
            continue
        bindings.append(source)
        if (
            source.speaker_id != actor_id
            or source.kind != "narration"
            or source.history is not None
        ):
            continue
        action = unique_span(message.content, source.text, source.action_span)
        if action and action.start <= span.start < span.end <= action.end:
            matched.append(source)
    if any(
        outcome.actor_id == actor_id
        and outcome.status == "blocked"
        and span.start < outcome.evidence_span.end
        and outcome.evidence_span.start < span.end
        and outcome.evidence_span.matches(message.content, outcome.evidence)
        for source in bindings
        for outcome in source.movement_outcomes
    ):
        return "blocked"
    return "reviewed" if matched else fallback


def _fallback(
    kernel: Any, actor: str, message: Any, span: EvidenceSpan
) -> Literal["fallback", "blocked", "unowned"]:
    from backend.engine.chpm.kernel import digest

    records = [
        row
        for row in (kernel.recovery.recent if kernel is not None else ())
        if row.reply_id == message.id
        and row.reply_revision == message.revision_id
        and row.reply_hash == digest(message.content)
        and actor in row.actor_ids
    ]
    if message.npc_recovery is None:
        return "fallback" if records else "unowned"
    try:
        audit = RecoveryAudit.model_validate(message.npc_recovery)
    except ValueError:
        return "unowned"
    if (audit.content_hash, audit.revision_id, audit.scene_id) != (
        digest(message.content),
        message.revision_id,
        message.scene_id or "",
    ):
        return "unowned"
    if any(
        row.actor_id == actor
        and row.status == "blocked"
        and span.start < row.evidence_span.end
        and row.evidence_span.start < span.end
        and row.evidence_span.matches(message.content, row.evidence)
        for row in audit.movement_outcomes
    ):
        return "blocked"
    return "fallback" if actor in audit.actors or records else "unowned"
