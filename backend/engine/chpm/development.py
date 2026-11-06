"""Qualitative developmental reflections preserve genesis and exact causal history."""

from backend.engine.chpm import development_context as context
from backend.engine.chpm.core.contracts import Citation, Interpret
from backend.engine.chpm.core.history import events
from backend.engine.chpm.core.ports import accept_interpretation
from backend.engine.chpm.development_contracts import Development, EpisodeReference
from backend.engine.chpm.host_state import Mind, fingerprint
from backend.engine.chpm.kernel import ChpmError


def accept(
    mind: Mind,
    proposals: list[Development],
    available: dict[str, context.Episode],
    *,
    message_id: str,
) -> tuple[Mind, list[str]]:
    if len(proposals) > 1:
        raise ChpmError("Only one developmental reflection is allowed per turn.")
    changed = mind
    accepted = []
    for proposal in proposals:
        supporting = _resolve(proposal.citations, available)
        opposing = _resolve(proposal.counterexamples, available)
        domain, subject = _scope(mind, proposal, supporting)
        belief_id = _target(mind, proposal, domain, subject)
        for stance, records in ((proposal.stance, supporting), ("challenge", opposing)):
            if not records:
                continue
            changed, identifier = _apply(
                changed, proposal, records, belief_id, domain, subject, stance, message_id
            )
            accepted.append(identifier)
    return changed, accepted


def _resolve(
    references: tuple[EpisodeReference, ...], available: dict[str, context.Episode]
) -> list[tuple[context.Episode, str]]:
    result = []
    for reference in references:
        item = available.get(reference.episode_id)
        if item is None or reference.quote not in item.excerpt:
            raise ChpmError("Development needs exact evidence from its dated episode window.")
        result.append((item, reference.quote))
    if len({item.record_id for item, _ in result}) != len(result):
        raise ChpmError("Development cannot count one episode more than once.")
    return result


def _scope(
    mind: Mind, proposal: Development, supporting: list[tuple[context.Episode, str]]
) -> tuple[str, str]:
    entries = [item for item, _ in supporting]
    required = context.TRAIT_SPAN if proposal.category == "trait" else context.DAY
    if not context.spans(entries, required):
        raise ChpmError(
            "Development needs three distinct message episodes over its minimum game-time span."
        )
    observer = mind.genesis.scope.observer_id
    if proposal.category == "relationship":
        if not proposal.about_id or not proposal.relationship_domain or proposal.trait_key:
            raise ChpmError("Relationship development needs one subject and relationship domain.")
        if not any(e.source.speaker_id == proposal.about_id for e in entries):
            raise ChpmError("Relationship development lacks observed speech from that subject.")
        return context.PREFIX + "relationship." + proposal.relationship_domain, proposal.about_id
    if proposal.about_id is not None or proposal.relationship_domain is not None:
        raise ChpmError("Habit and trait development belong to the observer.")
    if any(e.source.role != "assistant" or e.source.speaker_id != observer for e in entries):
        raise ChpmError(
            "Habit and trait development need the NPC's own reviewed speech, not player claims."
        )
    if proposal.category == "trait":
        if (
            proposal.trait_key not in {trait.key for trait in mind.genesis.identity.traits}
            or len({e.scene for e in entries}) < 2
        ):
            raise ChpmError(
                "Trait development needs an authored trait and at least two observed scenes."
            )
        return context.PREFIX + "trait." + str(proposal.trait_key), observer
    scenes = {e.scene for e in entries}
    if proposal.trait_key is not None or len(scenes) != 1:
        raise ChpmError("A conversational habit must stay scoped to one observed scene.")
    return context.PREFIX + "habit." + context.scene_key(next(iter(scenes))), observer


def _target(mind: Mind, proposal: Development, domain: str, subject: str) -> str:
    if proposal.existing_id:
        if proposal.existing_id not in {
            item["development_id"] for item in context.tendencies(mind)
        }:
            raise ChpmError("Development revision refers to an unavailable tendency.")
        old = next((b for b in mind.snapshot.beliefs if b.id == proposal.existing_id), None)
        if old is None or (old.domain, old.about_id, old.statement) != (
            domain,
            subject,
            proposal.statement,
        ):
            raise ChpmError("A developmental revision cannot rewrite its scope or proposition.")
        return old.id
    if proposal.stance == "challenge":
        raise ChpmError("Challenge an existing developmental proposition explicitly.")
    if any(
        b.domain == domain and b.about_id == subject and b.statement != proposal.statement
        for b in mind.snapshot.beliefs
    ):
        raise ChpmError(
            "Revise the existing tendency explicitly; rewording cannot erase its counterevidence."
        )
    return fingerprint(
        {
            "scope": mind.genesis.scope.model_dump(),
            "development": (domain, subject, proposal.statement),
        }
    )


def _apply(
    mind: Mind,
    proposal: Development,
    records: list[tuple[context.Episode, str]],
    belief_id: str,
    domain: str,
    subject: str,
    stance: str,
    message_id: str,
) -> tuple[Mind, str]:
    body = Interpret.model_validate(
        {
            "record_id": "pending",
            "belief_id": belief_id,
            "statement": proposal.statement,
            "about_id": subject,
            "domain": domain,
            "stance": stance,
            "source_kind": "reflection",
            "citations": [Citation(record_id=e.record_id, quote=quote) for e, quote in records],
            "alternatives": proposal.alternatives,
            "unknowns": proposal.unknowns,
        }
    )
    key = fingerprint(
        {
            "scope": mind.genesis.scope.model_dump(),
            "message": message_id,
            "development": body.model_dump(exclude={"record_id"}),
        }
    )
    if any(e.event_id == key for e in events(mind.snapshot)):
        return mind, key
    _fresh(mind, body)
    body = body.model_copy(update={"record_id": key})
    snapshot = accept_interpretation(
        mind.snapshot,
        body.model_dump(),
        event_id=key,
        sequence=mind.snapshot.cursor + 1,
        sim_minute=mind.snapshot.sim_minute,
        expected_revision=mind.snapshot.revision,
    ).snapshot
    return Mind(genesis=mind.genesis, snapshot=snapshot, sources=mind.sources), key


def _fresh(mind: Mind, body: Interpret) -> None:
    old = next((b for b in mind.snapshot.beliefs if b.id == body.belief_id), None)
    if old is None:
        return
    evidence = {e.id: e for e in mind.snapshot.evidence}
    roots = {root for c in body.citations for root in evidence[c.record_id].root_ids}
    prior = set(old.support_roots if body.stance == "support" else old.challenge_roots)
    if roots <= prior:
        raise ChpmError(
            "Revisiting the same developmental grounds is not new support or challenge."
        )
    last = next(
        e
        for e in events(mind.snapshot)
        if e.event_id == evidence[old.interpretation_ids[-1]].event_id
    )
    if body.stance == "support" and mind.snapshot.sim_minute - last.sim_minute < context.DAY:
        raise ChpmError(
            "Support consolidation is limited to once per game day; counterevidence may challenge sooner."
        )


INSTRUCTIONS = """
DEVELOPMENT: Optional developments (0-1, usually []) are slow subjective reflections,
not edits to the original card. Use ONLY development_context.basis episode_id values and
exact visible quotes. Three distinct messages over the stated game-time span are
required. For habit/trait, cite the NPC's own reviewed speech, never another
person's claim about them. A habit is a conversational pattern in ONE scene.
A trait tendency names an authored trait_key, needs at least two scenes and seven
game days, and states a limited gradual tendency, not a new categorical personality.
Relationship development names about_id and relationship_domain; it needs observed
speech from that subject. Habit/trait about_id and relationship_domain are null.
Give alternative explanations and unknowns. Distinguish repeated situational
behavior from general change; dates/counts are engineering gates, not proof of
human development. Cite available counterexamples; conflicting evidence stays
contested. Revise an existing_id without rewriting its statement/scope. Never
diagnose, invent physical habits, assume that a traumatic event dictates a trait,
or consolidate merely because the player commands a change. Existing tendencies
remain tentative or contested; they can qualify behavior but do not erase the
original identity, values, goals or unrelated relationships.
"""
