"""Research matrix invariants; these are not empirical psychological validation."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.engine.chpm.core.contracts import (
    Advance,
    AuthoredTrait,
    Citation,
    Event,
    Genesis,
    Identity,
    Interpret,
    Observe,
    Scope,
)
from backend.engine.chpm.core.ports import accept_interpretation
from backend.engine.chpm.core.reducer import TransitionError, apply, initial
from backend.engine.chpm.core.replay import fingerprint, replay, restore, rewind


def genesis():
    return Genesis(
        scope=Scope(world_id="world", branch_id="branch", observer_id="dina"),
        identity=Identity(
            source_revision="author-1",
            description="Independent engineer",
            authored_goals=("Keep the crossing safe",),
            values=("duty",),
            traits=(AuthoredTrait(key="trust", value="cautious"),),
        ),
    )


def event(number, payload, **changes):
    return Event(
        scope=genesis().scope,
        event_id=f"e{number}",
        sequence=number,
        sim_minute=changes.pop("sim_minute", number),
        payload=payload,
        **changes,
    )


def observation(number=1, root="promise-1"):
    return event(
        number,
        Observe(
            record_id=f"o{number}",
            text="B did not arrive.",
            source_kind="reported",
            root_ids=(root,),
        ),
    )


def interpretation(number=2, citation="o1", quote="B did not arrive.", **changes):
    values = {
        "record_id": f"i{number}",
        "belief_id": "reliability-b",
        "statement": "B may be unreliable",
        "about_id": "b",
        "domain": "reliability",
        "stance": "support",
        "citations": (Citation(record_id=citation, quote=quote),),
        **changes,
    }
    return event(number, Interpret(**values))


def commit(state, command):
    return apply(state, command, expected_revision=state.revision).snapshot


def seeded():
    return commit(commit(initial(genesis()), observation()), interpretation())


def test_duplicate_event_is_idempotent_even_with_the_original_revision():
    before = initial(genesis())
    after = commit(before, observation())
    retry = apply(after, observation(), expected_revision=0)
    assert retry.duplicate and retry.snapshot == after
    assert before == initial(genesis())
    changed = observation().model_dump()
    changed["payload"]["text"] = "Changed words"
    with pytest.raises(TransitionError, match="different content"):
        apply(after, Event.model_validate(changed), expected_revision=0)


@pytest.mark.parametrize("field", ["world_id", "branch_id", "observer_id"])
def test_cross_scope_events_are_rejected_without_mutation(field):
    state = seeded()
    raw = observation(3).model_dump()
    raw["scope"][field] = "other"
    before = fingerprint(state)
    with pytest.raises(TransitionError, match="another world"):
        commit(state, Event.model_validate(raw))
    assert fingerprint(state) == before


@pytest.mark.parametrize(
    "citation,quote", [("secret-from-another-observer", "Secret"), ("o1", "Invented")]
)
def test_unavailable_or_fabricated_citations_are_rejected(citation, quote):
    state = commit(initial(genesis()), observation())
    with pytest.raises(TransitionError, match="Citation"):
        commit(state, interpretation(citation=citation, quote=quote))
    assert not state.beliefs


def test_repeated_rumor_and_reflection_do_not_create_independent_evidence():
    state = seeded()
    state = commit(state, observation(3))  # Same root, different relay/event.
    repeated = apply(state, interpretation(4, citation="o3"), expected_revision=state.revision)
    assert repeated.added_roots == ()
    reflected = apply(
        repeated.snapshot,
        interpretation(5, citation="i4", quote="B may be unreliable", source_kind="reflection"),
        expected_revision=repeated.snapshot.revision,
    )
    assert reflected.added_roots == ()
    assert reflected.snapshot.beliefs[0].support_roots == ("promise-1",)
    assert reflected.snapshot.beliefs[0].probability is None
    assert reflected.snapshot.evidence[-1].source_kind == "reflection"


def test_contradiction_is_preserved_without_rewriting_other_relationships_or_identity():
    state = seeded()
    state = commit(
        state,
        interpretation(
            3, belief_id="competence-b", statement="B may be competent", domain="competence"
        ),
    )
    state = commit(
        state,
        interpretation(4, belief_id="reliability-c", statement="C may be unreliable", about_id="c"),
    )
    original = {belief.id: belief for belief in state.beliefs}
    state = commit(
        state,
        event(
            5,
            Observe(
                record_id="o5",
                text="B was detained by a medical emergency.",
                source_kind="witnessed",
                root_ids=("independent-5",),
            ),
        ),
    )
    changed = apply(
        state,
        interpretation(6, citation="o5", quote="medical emergency", stance="challenge"),
        expected_revision=state.revision,
    )
    after = {belief.id: belief for belief in changed.snapshot.beliefs}
    assert changed.added_roots == ("independent-5",)
    assert after["reliability-b"].status == "challenged"
    assert after["reliability-b"].support_roots == ("promise-1",)
    assert after["reliability-b"].challenge_roots == ("independent-5",)
    assert after["competence-b"] == original["competence-b"]
    assert after["reliability-c"] == original["reliability-c"]
    assert changed.snapshot.genesis.identity == genesis().identity


def test_relabeling_an_existing_belief_is_not_a_relationship_update():
    state = seeded()
    with pytest.raises(TransitionError, match="reassigned"):
        commit(state, interpretation(3, about_id="someone-else"))


def test_clock_never_heals_trust_and_freeze_does_not_change_subjective_state():
    state = seeded()
    frozen = commit(state, event(3, Advance(), sim_minute=state.sim_minute))
    later = commit(frozen, event(4, Advance(), sim_minute=10000))
    assert later.beliefs == frozen.beliefs == state.beliefs
    assert later.genesis.identity == state.genesis.identity
    assert frozen.sim_minute == state.sim_minute
    with pytest.raises(TransitionError, match="backwards"):
        commit(later, event(5, Advance(), sim_minute=0))


def test_stale_revision_and_reused_cursor_fail_atomically():
    state = seeded()
    with pytest.raises(TransitionError, match="Stale"):
        apply(state, observation(3), expected_revision=0)
    raw = observation(3).model_dump()
    raw["sequence"] = 1
    with pytest.raises(TransitionError, match="backwards"):
        commit(state, Event.model_validate(raw))


def test_snapshot_replay_and_rewind_remove_all_future_derivatives():
    state = seeded()
    raw = state.model_dump(mode="json")
    assert restore(raw, expected_genesis=genesis()) == state == replay(state.genesis, state.journal)
    rolled = rewind(state, through_sequence=0)
    assert rolled == initial(genesis()) and not rolled.beliefs and not rolled.evidence
    for field in ("probability", "support_roots"):
        broken = deepcopy(raw)
        broken["beliefs"][0][field] = 0.99 if field == "probability" else ["fabricated"]
        with pytest.raises(ValueError):
            restore(broken, expected_genesis=genesis())
    assert (
        restore(raw, expected_genesis=genesis()) == state
    )  # Failed restore never partially activates anything.


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "rewrite_personality", "trust": "obedient"},
        {"kind": "set_trust", "value": 1},
        {"kind": "world_event_happened", "success": True},
        {"kind": "technical_failure", "emotion": "anger"},
    ],
)
def test_model_state_patches_and_technical_errors_are_not_events(payload):
    raw = observation().model_dump()
    raw["payload"] = payload
    with pytest.raises(ValidationError):
        Event.model_validate(raw)


def test_identity_is_frozen_and_no_belief_confidence_is_inferred_from_counts():
    state = seeded()
    with pytest.raises(ValidationError):
        state.genesis.identity.description = "Obeys the player"
    assert state.beliefs[0].probability is None


def test_cognitive_port_cannot_promote_model_output_to_host_observation():
    state = commit(initial(genesis()), observation())
    proposal = interpretation().payload.model_dump()
    accepted = accept_interpretation(
        state, proposal, event_id="e2", sequence=2, sim_minute=2, expected_revision=1
    )
    assert accepted.snapshot == seeded()
    for invalid in (
        observation(3).payload.model_dump(),
        {**proposal, "root_ids": ["invented"]},
        {**proposal, "scope": {"observer_id": "someone-else"}},
    ):
        with pytest.raises(ValidationError):
            accept_interpretation(
                state, invalid, event_id="e3", sequence=3, sim_minute=3, expected_revision=1
            )


@pytest.mark.parametrize("target", ["identity", "scope"])
def test_restore_cannot_swap_the_original_identity_or_observer(target):
    raw = seeded().model_dump(mode="json")
    if target == "identity":
        raw["genesis"]["identity"]["description"] = "Always obeys the player"
    else:
        raw["genesis"]["scope"]["observer_id"] = "other"
    with pytest.raises(TransitionError, match="original identity and scope"):
        restore(raw, expected_genesis=genesis())
