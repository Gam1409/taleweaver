"""Pure contracts: unknown, ordering, evidence, replay, and reversible storage."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.engine.chpm.appraisal_contracts import GroundedProposal
from backend.engine.chpm.kernel import ChpmError, existing, select
from backend.engine.chpm.schema import Candidate, KernelState, Observation, Proposal, Settings
from backend.engine.chpm.state import controls, load, retract, save


def observation(**changes):
    return Observation.model_validate(
        {
            "session_id": "session",
            "message_id": "input",
            "content_hash": "hash",
            "sequence": 10,
            "scene_id": "room",
            "minute": 5,
            "player_request": "Please help.",
            **changes,
        }
    )


def proposal():
    return Proposal(
        candidates=[
            Candidate(
                kind="CONTINUE",
                intention="Discuss the repair",
                goal_alignment="supports",
                goal_quote="Repair the bridge",
                reconsider_if="The repair is completed",
            ),
            Candidate(
                kind="DEFER", intention="Remain silent", reconsider_if="A new request arrives"
            ),
        ],
        appraisal="The request may help the authored goal.",
    )


def decision(**changes):
    return select(
        "npc", observation(**changes), proposal(), goal="Repair the bridge", context_hash="context"
    )


def grounded_proposal():
    value = proposal()
    return GroundedProposal(
        candidates={
            candidate.kind: candidate.model_dump(exclude={"kind"}) for candidate in value.candidates
        },
        interpretations=[],
    )


def test_deterministic_choice_does_not_depend_on_candidate_order():
    candidates = proposal()
    before = candidates.model_dump()
    first = decision()
    candidates.candidates.reverse()
    second = select(
        "npc", observation(), candidates, goal="Repair the bridge", context_hash="context"
    )
    assert first.selected == second.selected
    assert first.selected.kind == "CONTINUE"
    assert proposal().model_dump() == before


def test_duplicate_and_stale_observations_do_not_advance_state():
    first = decision()
    assert existing(first, observation(), "context") == first
    with pytest.raises(ChpmError, match="source changed"):
        existing(first, observation(content_hash="edited"), "context")
    with pytest.raises(ChpmError, match="older"):
        existing(first, observation(message_id="older", sequence=9), "context")
    assert existing(first, observation(message_id="new", sequence=11), "context") is None


@pytest.mark.parametrize("kind", ["duplicate", "unsupported", "false-quote"])
def test_rejects_untrusted_goal_claims_and_duplicate_kinds(kind):
    supplied = proposal()
    if kind == "duplicate":
        supplied.candidates[1].kind = "CONTINUE"
    elif kind == "unsupported":
        supplied.candidates[0].goal_quote = "She now fully trusts the player"
    else:
        supplied.candidates[1].goal_quote = "Repair the bridge"
    with pytest.raises(ChpmError):
        select("npc", observation(), supplied, goal="Repair the bridge", context_hash="context")


def test_missing_alignment_is_unknown_not_zero():
    candidate = Candidate(kind="DEFER", intention="Wait", reconsider_if="Someone speaks")
    assert candidate.goal_alignment == "unknown"
    with pytest.raises(ValidationError):
        Candidate(kind="DEFER", intention="Wait", reconsider_if="Someone speaks", goal_alignment=0)


def test_defaults_and_request_budget():
    assert Settings().mode == "off"
    with pytest.raises(ValidationError):
        Settings(mode="live")
    with pytest.raises(ValidationError):
        Settings(mode="live", actor_ids=["a", "b"], max_calls_per_turn=2)
    with pytest.raises(ValidationError):
        Settings(mode="shadow", actor_ids=["a", "a"])


def test_state_is_copy_on_write_fenced_and_retractable():
    host = SimpleNamespace(entity_states={"npc": {"hp": 8}})
    assert not controls(host, "npc")
    value = KernelState(
        settings=Settings(mode="live", actor_ids=["npc"]), actors={"npc": decision()}
    )
    save(host, value, expected_revision=0)
    assert value.revision == 0
    assert load(host).revision == 1
    assert host.entity_states["npc"] == {"hp": 8}
    assert controls(host, "npc")
    with pytest.raises(ChpmError, match="state changed"):
        save(host, value, expected_revision=0)
    retract(host, "an-earlier-source-that-may-be-an-indirect-dependency")
    assert load(host).actors == {}
    assert host.entity_states["npc"] == {"hp": 8}


def test_replay_accepted_proposal_needs_no_llm_or_wall_clock():
    saved = decision().model_dump_json()
    from backend.engine.chpm.schema import Decision

    restored = Decision.model_validate_json(saved)
    replayed = select(
        "npc",
        restored.observation,
        restored.proposal,
        goal="Repair the bridge",
        context_hash=restored.context_hash,
    )
    assert replayed == restored
