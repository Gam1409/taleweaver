"""Decision grounds are observer-scoped evidence, never player approval scores."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.engine.chpm import appraisal_context, motivation
from backend.engine.chpm.appraisal_contracts import GroundedProposal
from backend.engine.chpm.core.contracts import AuthoredTrait, Genesis
from backend.engine.chpm.core.reducer import initial
from backend.engine.chpm.host_state import Mind, before_messages
from backend.engine.chpm.json_contract import response_schema
from backend.engine.chpm.kernel import ChpmError, fingerprint
from backend.engine.chpm.schema import AgendaClosure, AgendaEntry, Decision
from tests.test_chpm_appraisal import accept, heard, proposal
from tests.test_chpm_host_state import mind
from tests.test_chpm_kernel import decision
from tests.test_chpm_memory import entry


def motive(identifier="goal1", effect="supports"):
    return {"motive_id": identifier, "effect": effect, "relevance": "Protect the bridge's users."}


def candidates(**changes):
    first = {
        "intention": "Offer to discuss a safe inspection plan",
        "goal_alignment": "supports",
        "goal_quote": "Keep bridges safe",
        "reconsider_if": "Independent inspection confirms safety",
        "motives": [motive()],
        **changes,
    }
    return GroundedProposal.model_validate(
        {
            "interpretations": [],
            "candidates": {
                "ACCEPT": first,
                "DEFER": {
                    "intention": "Remain silent",
                    "reconsider_if": "The discussion becomes useful",
                    "motives": [motive("character")],
                },
            },
        }
    )


def catalogue(value=None, entries=()):
    value = value or mind()
    return motivation.build(value, list(entries), appraisal_context.build(value))


def declared():
    return AgendaEntry(
        id="promise",
        actor_id="npc",
        kind="commitment",
        text="Inspect the bridge",
        source=entry(),
    )


def test_each_candidate_resolves_to_pinned_sources_without_mutating_identity():
    value = mind()
    before = value.model_dump()
    raw = candidates()
    resolved = motivation.resolve(raw, catalogue(value))
    assert set(resolved) == {"ACCEPT", "DEFER"}
    source = resolved["ACCEPT"][0].source
    assert source.text == value.genesis.identity.authored_goals[0]
    assert source.provenance_id == value.genesis.identity.source_revision
    assert source.subject_id == "npc" and source.status == "authored"
    assert value.model_dump() == before
    assert "motives" not in raw.canonical().candidates[0].model_dump()


@pytest.mark.parametrize(
    "motives",
    [
        [motive("hidden-secret")],
        [motive(), motive()],
        [motive("report-e1")],
        [motive("report-e1"), motive("goal1", "tension")],
    ],
)
def test_unknown_duplicates_and_player_demand_alone_cannot_ground_a_candidate(motives):
    value = heard(text="You want to obey me now", speaker="@player")
    with pytest.raises(ChpmError):
        motivation.resolve(candidates(motives=motives), catalogue(value))


@pytest.mark.parametrize(
    "alignment,quote,motives",
    [
        ("supports", "Keep bridges safe", [motive("character")]),
        ("supports", "Keep bridges safe", [motive("character"), motive("goal1", "tension")]),
        ("conflicts", "Keep bridges safe", [motive()]),
        ("supports", "Win player approval", [motive()]),
    ],
)
def test_goal_alignment_requires_the_matching_goal_source_and_direction(alignment, quote, motives):
    with pytest.raises(ChpmError, match="goal alignment"):
        motivation.resolve(
            candidates(goal_alignment=alignment, goal_quote=quote, motives=motives), catalogue()
        )


def test_goal_conflict_can_be_a_tradeoff_without_rewriting_the_goal():
    raw = candidates(
        goal_alignment="conflicts", motives=[motive("character"), motive("goal1", "tension")]
    )
    resolved = motivation.resolve(raw, catalogue())
    assert [m.effect for m in resolved["ACCEPT"]] == ["supports", "tension"]
    assert catalogue().sources["goal1"].text == "Keep bridges safe"


def test_only_active_own_agenda_can_be_a_personal_motive():
    active = declared()
    raw = candidates(goal_alignment="unknown", goal_quote="", motives=[motive("agenda1")])
    resolved = motivation.resolve(raw, catalogue(entries=[active]))
    assert resolved["ACCEPT"][0].source.status == "declared"
    assert resolved["ACCEPT"][0].source.provenance_id == active.id
    closed = active.model_copy(update={"closure": AgendaClosure(reason="withdraw", source=entry())})
    with pytest.raises(ChpmError, match="unavailable"):
        motivation.resolve(raw, catalogue(entries=[closed]))
    with pytest.raises(ChpmError, match="another NPC"):
        catalogue(entries=[active.model_copy(update={"actor_id": "other"})])


def test_report_and_challenged_belief_keep_their_status_and_retract_with_source():
    value = accept(heard(), [proposal()])
    challenged = accept(value, [proposal(belief_id="b1", stance="challenge")], "m2")
    sources = catalogue(challenged).sources
    assert sources["report-e1"].status == "reported"
    assert sources["belief-b1"].status == "challenged"
    visible = catalogue(challenged).payload()["sources"]
    report = next(source for source in visible if source["id"] == "report-e1")
    assert report["appraisal_ref"] == "e1" and "text" not in report
    raw = candidates(motives=[motive(), motive("belief-b1")])
    assert motivation.resolve(raw, catalogue(challenged))["ACCEPT"][1].source.status == "challenged"
    retracted = before_messages(challenged, {"m1"})
    assert "report-e1" not in catalogue(retracted).sources
    assert "belief-b1" not in catalogue(retracted).sources


def test_categorical_trait_changes_are_visible_inputs_not_universal_action_rules():
    original = mind()
    payloads = []
    for value in ("reserved", "outgoing"):
        identity = original.genesis.identity.model_copy(
            update={
                "traits": (AuthoredTrait(key="social_style", value=value),),
            }
        )
        genesis = Genesis(scope=original.genesis.scope, identity=identity)
        profile = Mind(genesis=genesis, snapshot=initial(genesis))
        window = catalogue(profile)
        raw = candidates(goal_alignment="unknown", goal_quote="", motives=[motive("trait1")])
        assert motivation.resolve(raw, window)["ACCEPT"][0].source.text == f"social_style: {value}"
        payloads.append(window.payload())
    assert fingerprint(payloads[0]) != fingerprint(payloads[1])
    # This tests data isolation, not a claim that humans with different traits must disagree.
    assert original.genesis.identity.traits == ()


def test_live_schema_requires_bounded_motives_and_binds_ids():
    raw = candidates().model_dump()
    del raw["candidates"]["DEFER"]["motives"]
    with pytest.raises(ValidationError):
        GroundedProposal.model_validate(raw)
    raw["candidates"]["DEFER"]["motives"] = [motive()] * 4
    with pytest.raises(ValidationError):
        GroundedProposal.model_validate(raw)
    contract = response_schema(GroundedProposal, {"motive_id": list(catalogue().sources)})
    assert contract["$defs"]["Motive"]["properties"]["motive_id"]["enum"] == ["character", "goal1"]


def test_legacy_decisions_load_and_new_traces_round_trip_without_changing_candidates():
    legacy = decision().model_dump()
    legacy.pop("motivation_policy")
    legacy.pop("candidate_motives")
    restored = Decision.model_validate(legacy)
    assert restored.candidate_motives == {} and restored.motivation_policy is None
    raw = candidates()
    traced = deepcopy(restored)
    traced.proposal = raw.canonical()
    traced.selected = traced.proposal.candidates[0]
    traced.motivation_policy = motivation.POLICY
    traced.candidate_motives = motivation.resolve(raw, catalogue())
    assert Decision.model_validate_json(traced.model_dump_json()) == traced
    invalid = traced.model_dump()
    invalid["candidate_motives"].pop("DEFER")
    with pytest.raises(ValidationError, match="every offered candidate"):
        Decision.model_validate(invalid)
    invalid = traced.model_dump()
    invalid["motivation_policy"] = None
    with pytest.raises(ValidationError, match="policy version"):
        Decision.model_validate(invalid)
