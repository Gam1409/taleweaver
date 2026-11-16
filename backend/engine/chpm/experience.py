"""Fallible affect/need appraisals with current sources and an explicit freshness policy."""

from backend.engine.chpm.appraisal_context import Window
from backend.engine.chpm.appraisal_contracts import FeltExperience
from backend.engine.chpm.core.contracts import Citation, Event, Experience, PersonalBasis
from backend.engine.chpm.core.history import events
from backend.engine.chpm.core.reducer import apply
from backend.engine.chpm.host_state import Mind, fingerprint
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.motivation import Catalogue
from backend.engine.chpm.observation_sources import current

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


def used_observations(mind: Mind, record_ids: set[str]) -> dict[str, list[str]]:
    evidence = {row.id: row for row in mind.snapshot.evidence}
    estimates = view(mind)["states"]
    return {
        key: [
            row["state_id"]
            for row in estimates
            if set(evidence[key].root_ids) <= set(evidence[row["record_id"]].root_ids)
        ]
        for key in record_ids
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
    if any(source and source[1].kind == "host_frame" for source in references):
        raise ChpmError("Use a specific host observation, not a whole frame, for experience.")
    observed = current(mind, message_id)
    if not any(
        source
        and (
            source[0] in observed
            if source[1].kind == "host_observation"
            else source[1].message_id == message_id
        )
        for source in references
    ):
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
EXPERIENCE: Return 0-2 tentative observer appraisals, [] if unwarranted, separate from beliefs.
Each needs exact visible citations, a CURRENT observed trigger, authored/active-agenda
personal_motive_ids, explanation, alternatives and unknowns. Explain personal significance
from situation, identity and accessible history. Motive IDs ground stakes, not permission
to feel. Mixed feelings and controlled expression can coexist with strong feeling.
For affect use fear/anger/sadness/joy/shame/interest/arousal/sexual_desire. arousal denotes
general activation; sexual_desire denotes sexual wanting. about_id is a known target or null.
For need_satisfaction/need_frustration use autonomy/competence/relatedness/rest/safety,
about_id=null. Satisfaction and frustration are independent; low satisfaction does not
establish frustration. Apply the same contextual appraisal rules to every dimension.
Levels: absent/low/moderate/high. Omission is unassessed; historical_current_unknown means
unknown current intensity, not calm. Time alone does not establish recovery.
Estimates update their own dimensions; identity, choices, beliefs and world facts keep
their owners. Attributed feelings remain reports. Ground appraisals before choosing actions.
Cite current_turn=true or currently_observed=true evidence. Current access is not a new
event. already_supports_states identifies reused grounds: retain those estimates without
refreshing/intensifying from the same evidence. Recall alone supplies no new grounds.
Cite specific observations; whole host_frame, last_observed_scene and history are context.
These categories and freshness horizons are engineering policy, not clinical laws.
"""
