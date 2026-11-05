"""Validate cognitive interpretations and stamp causal events before intent selection."""

from backend.engine.chpm.appraisal_context import Window
from backend.engine.chpm.appraisal_contracts import Assessment, Revision
from backend.engine.chpm.core.contracts import Citation, Interpret
from backend.engine.chpm.core.history import events
from backend.engine.chpm.core.ports import accept_interpretation
from backend.engine.chpm.host_state import Mind, fingerprint
from backend.engine.chpm.kernel import ChpmError


def accept(
    mind: Mind, proposals: list[Assessment | Revision], window: Window, *, message_id: str
) -> tuple[Mind, list[str]]:
    snapshot = mind.snapshot
    accepted: list[str] = []
    seen: set[str] = set()
    for proposal in proposals:
        body = _interpretation(mind, proposal, window, message_id)
        if body.belief_id in seen:
            raise ChpmError("CHPM appraisal repeats a proposition in one batch.")
        seen.add(body.belief_id)
        accepted.append(body.record_id)
        if any(event.event_id == body.record_id for event in events(snapshot)):
            continue
        snapshot = accept_interpretation(
            snapshot,
            body.model_dump(),
            event_id=body.record_id,
            sequence=snapshot.cursor + 1,
            sim_minute=snapshot.sim_minute,
            expected_revision=snapshot.revision,
        ).snapshot
    return Mind(genesis=mind.genesis, snapshot=snapshot, sources=mind.sources), accepted


def _interpretation(
    mind: Mind, proposal: Assessment | Revision, window: Window, message_id: str
) -> Interpret:
    belief_id, about_id, domain, statement = _target(mind, proposal, window)
    if about_id not in window.subjects:
        raise ChpmError("CHPM appraisal refers to an unavailable subject.")
    citations = []
    for reference in proposal.citations:
        source = window.sources.get(reference.source_id)
        if source is None or reference.quote not in source[2]:
            raise ChpmError("CHPM appraisal needs exact evidence from its visible window.")
        citations.append(Citation(record_id=source[0], quote=reference.quote))
    if len({(citation.record_id, citation.quote) for citation in citations}) != len(citations):
        raise ChpmError("CHPM appraisal repeats the same citation.")
    body = Interpret(
        record_id="pending",
        belief_id=belief_id,
        statement=statement,
        about_id=about_id,
        domain=domain,
        stance=proposal.stance,
        citations=tuple(sorted(citations, key=lambda c: (c.record_id, c.quote))),
        alternatives=proposal.alternatives,
        unknowns=proposal.unknowns,
    )
    event_id = fingerprint(
        {
            "kind": "appraisal",
            "scope": mind.genesis.scope.model_dump(),
            "message_id": message_id,
            "body": body.model_dump(exclude={"record_id"}),
        }
    )
    return body.model_copy(update={"record_id": event_id})


def _target(
    mind: Mind, proposal: Assessment | Revision, window: Window
) -> tuple[str, str, str, str]:
    if isinstance(proposal, Revision):
        old = window.beliefs.get(proposal.belief_id)
        if old is None:
            raise ChpmError("CHPM appraisal refers to an unavailable belief.")
        return old.id, old.about_id, old.domain, old.statement
    key = (proposal.about_id, proposal.domain, proposal.statement)
    old = next(
        (b for b in mind.snapshot.beliefs if (b.about_id, b.domain, b.statement) == key), None
    )
    if old is not None:
        return old.id, *key
    return fingerprint({"scope": mind.genesis.scope.model_dump(), "proposition": key}), *key
