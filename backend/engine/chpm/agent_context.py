"""Carry retrieved facts through narration/review, not just the intent proposal."""

from backend.engine.chpm.host_state import Mind, Source
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import (
    AgentEvidence,
    Decision,
    Observation,
    validate_agent_evidence,
)


def collect(pins: dict[str, tuple[str, Source, str]], observed: Observation) -> list[AgentEvidence]:
    evidence = [
        AgentEvidence(
            source_id=alias,
            record_id=key,
            source_message_id=source.message_id,
            source_revision_id=source.revision_id,
            source_hash=source.content_hash,
            speaker_id=source.speaker_id,
            kind="reported" if source.kind == "speech" else "witnessed",
            text=text,
            current_turn=source.message_id == observed.message_id,
        )
        for alias, (key, source, text) in pins.items()
    ]
    try:
        validate_agent_evidence(evidence)
    except ValueError as exc:
        raise ChpmError("CHPM agent handoff is invalid: " + str(exc)) from exc
    return evidence


def present(decision: Decision, mind: Mind) -> list[dict]:
    if not decision.agent_evidence:
        return []
    scope = mind.genesis.scope
    if scope.world_id != decision.observation.session_id or scope.observer_id != decision.actor_id:
        raise ChpmError("Agent evidence belongs to another session or observer.")
    for entry in decision.agent_evidence:
        source = mind.sources.get(entry.record_id)
        if source is None or not _matches(entry, source, decision.observation):
            raise ChpmError("Agent evidence is stale or differs from its observed source.")
    return [
        entry.model_dump(exclude={"source_hash", "source_revision_id"})
        for entry in decision.agent_evidence
    ]


def _matches(entry: AgentEvidence, source: Source, observed: Observation) -> bool:
    return (
        entry.source_message_id == source.message_id
        and entry.source_revision_id == source.revision_id
        and entry.source_hash == source.content_hash
        and entry.speaker_id == source.speaker_id
        and entry.text in source.text
        and entry.kind == ("reported" if source.kind == "speech" else "witnessed")
        and entry.current_turn == (source.message_id == observed.message_id)
    )
