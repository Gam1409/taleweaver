"""Fallible affect/need appraisals with current sources and an explicit freshness policy."""

from backend.engine.chpm.appraisal_context import Window
from backend.engine.chpm.appraisal_contracts import FeltExperience
from backend.engine.chpm.core.contracts import Citation, Event, Experience, PersonalBasis
from backend.engine.chpm.core.history import events
from backend.engine.chpm.core.reducer import apply
from backend.engine.chpm.host_state import Mind, fingerprint
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.motivation import Catalogue

POLICY = "qualitative-experience-v1"
# A visibility horizon, NOT a measured recovery rate or a transition to calm.
FRESH_MINUTES = 30
VISIBLE_LIMIT = 8


def view(mind: Mind) -> dict:
    entries = []
    for index, value in enumerate(reversed(mind.snapshot.experiences[-VISIBLE_LIMIT:]), 1):
        age = mind.snapshot.sim_minute - value.sim_minute
        entries.append(
            {
                "state_id": f"x{index}",
                "record_id": value.record_id,
                "channel": value.channel,
                "dimension": value.dimension,
                "about_id": value.about_id,
                "last_assessed_level": value.level,
                "assessed_at_minute": value.sim_minute,
                "elapsed_minutes": age,
                "status": "recent_appraisal"
                if age <= FRESH_MINUTES
                else "historical_current_unknown",
            }
        )
    return {
        "policy": POLICY,
        "freshness_horizon_minutes": FRESH_MINUTES,
        "states": entries,
        "omitted": max(0, len(mind.snapshot.experiences) - VISIBLE_LIMIT),
        "meaning": "subjective hypotheses; not traits, displayed expression, consent or diagnoses",
    }


def accept(
    mind: Mind,
    proposals: list[FeltExperience],
    window: Window,
    catalogue: Catalogue,
    *,
    message_id: str,
) -> tuple[Mind, list[str]]:
    snapshot = mind.snapshot
    accepted = []
    seen: set[tuple[str, str, str | None]] = set()
    for proposal in proposals:
        key = (proposal.channel, proposal.dimension, proposal.about_id)
        if key in seen:
            raise ChpmError("CHPM repeats an affect/need dimension in one batch.")
        seen.add(key)
        body = _resolve(mind, proposal, window, catalogue, message_id)
        accepted.append(body.record_id)
        if any(event.event_id == body.record_id for event in events(snapshot)):
            continue
        event = Event(
            scope=mind.genesis.scope,
            event_id=body.record_id,
            sequence=snapshot.cursor + 1,
            sim_minute=snapshot.sim_minute,
            payload=body,
        )
        snapshot = apply(snapshot, event, expected_revision=snapshot.revision).snapshot
    return Mind(genesis=mind.genesis, snapshot=snapshot, sources=mind.sources), accepted


def _resolve(
    mind: Mind,
    proposal: FeltExperience,
    window: Window,
    catalogue: Catalogue,
    message_id: str,
) -> Experience:
    if proposal.about_id is not None and proposal.about_id not in window.subjects:
        raise ChpmError("CHPM experience refers to an unavailable subject.")
    personal = [catalogue.sources.get(key) for key in proposal.personal_motive_ids]
    if any(
        item is None
        or item.status not in {"authored", "declared"}
        or item.subject_id != mind.genesis.scope.observer_id
        for item in personal
    ):
        raise ChpmError("CHPM experience needs this NPC's identity or active agenda basis.")
    references = [window.sources.get(c.source_id) for c in proposal.citations]
    if any(
        source is None or citation.quote not in source[2]
        for source, citation in zip(references, proposal.citations, strict=True)
    ):
        raise ChpmError("CHPM experience needs exact visible source evidence.")
    if not any(source and source[1].message_id == message_id for source in references):
        raise ChpmError("CHPM experience needs a current observed trigger, not recall alone.")
    citations = tuple(
        Citation(record_id=source[0], quote=citation.quote)
        for source, citation in zip(references, proposal.citations, strict=True)
        if source
    )
    if len(set(citations)) != len(citations):
        raise ChpmError("CHPM experience repeats a citation.")
    basis = tuple(
        PersonalBasis(reference=reference, text=text)
        for reference, text in sorted(
            {(item.provenance_id, item.text) for item in personal if item}
        )
    )
    body = Experience(
        record_id="pending",
        identity_revision=mind.genesis.identity.source_revision,
        channel=proposal.channel,
        dimension=proposal.dimension,
        about_id=proposal.about_id,
        level=proposal.level,
        citations=citations,
        personal_basis=basis,
        explanation=proposal.explanation,
        alternatives=proposal.alternatives,
        unknowns=proposal.unknowns,
    )
    key = fingerprint(
        {
            "kind": "experience",
            "scope": mind.genesis.scope.model_dump(),
            "message": message_id,
            "body": body.model_dump(exclude={"record_id"}),
        }
    )
    return body.model_copy(update={"record_id": key})


INSTRUCTIONS = """
EXPERIENCE: Return experiences (0-2, [] if unwarranted), separately from beliefs.
These are tentative estimates about this observer, not measurements or trait edits.
Each needs exact visible citations including a CURRENT observed trigger, authored/
active-agenda personal_motive_ids, a short explanation, alternatives and unknowns.
For affect use fear/anger/sadness/joy/shame/interest/arousal; arousal is general
activation, NOT sexual desire. about_id=null or a known subject. For need_satisfaction
or need_frustration use autonomy/competence/relatedness/rest/safety, about_id=null.
Satisfaction and frustration are independent; low satisfaction is not automatically
frustration. Levels are absent/low/moderate/high. Unknown means no estimate, not absent.
Mixed feelings and different outward expression are possible. Do not fill every
field, accept a player's attributed feeling as fact, diagnose illness, or infer
consent/obedience or lasting personality change. Repeated grounds or recall alone
cannot refresh/intensify a state. historical_current_unknown means current intensity
is unknown, not calm. Time alone never proves recovery. Consider recent appraisals
without counting them as independent evidence or rewriting values. Do not invent
feelings retrospectively to justify an action. No world/expression patch is authorized.
At least one citation for each new experience MUST have current_turn=true in
visible_evidence. Sources with false are historical; null means freshness is unknown.
Historical evidence can contextualize a current trigger, never replace it.
These categories and freshness horizons are engineering policy, not clinical laws.
"""
