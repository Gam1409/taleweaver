"""Compact narration keeps exact grounds and unresolved intention conditions."""

import json
from copy import deepcopy

import pytest

from backend.engine.chpm import appraisal_context, motivation, rendering, runtime, semantic_choice
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import Candidate, KernelState, PreviousIntention
from tests.test_chpm_host_state import mind
from tests.test_chpm_kernel import observation, preferred_choice, wire_proposal


def contract_fixture():
    value = mind()
    window = appraisal_context.build(value)
    catalogue = motivation.build(value, [], window)
    body = wire_proposal()
    for candidate in body["candidates"].values():
        candidate["motives"] = [
            {"motive_id": "character", "effect": "supports", "relevance": "Remain independent."}
        ]
    body["candidates"]["CONTINUE"]["intention"] = "Discuss signing after an inspection."
    body["candidates"]["CONTINUE"]["preconditions"] = ["The inspection is confirmed."]
    body["choice"] = preferred_choice(motive="character")
    raw = Draft.model_validate(body).materialize(catalogue)
    decision = semantic_choice.select(
        "npc",
        observation(),
        raw.canonical(),
        None,
        raw.choice,
        motivation.resolve(raw, catalogue),
        window,
        None,
        context_hash="compact",
    )
    return runtime.Turn(
        KernelState(), "input", decisions={"npc": decision}, minds={"npc": value}
    ), value


def test_precondition_survives_materialization_narrator_review_and_serialization():
    turn, _ = contract_fixture()
    chosen = turn.decisions["npc"]
    data = runtime.contract_data(turn)["npc"]
    assert data["preconditions"] == ["The inspection is confirmed."]
    assert (
        rendering._review_payload(turn, {}, "")["contract"]["npc"]["preconditions"]
        == data["preconditions"]
    )
    restored = KernelState.model_validate_json(
        KernelState(actors={"npc": chosen}).model_dump_json()
    )
    assert restored.actors["npc"].selected.preconditions == data["preconditions"]
    assert restored.schema_version == 6


def test_old_candidates_still_load_with_no_invented_conditions():
    old = {"kind": "CONTINUE", "intention": "Discuss the plan", "reconsider_if": "The plan changes"}
    assert Candidate.model_validate(old).preconditions == []


def test_existing_kernel_envelope_loads_decisions_without_the_additive_field():
    turn, _ = contract_fixture()
    saved = KernelState(actors=turn.decisions).model_dump()
    actor = saved["actors"]["npc"]
    actor["selected"].pop("preconditions")
    for candidate in actor["proposal"]["candidates"]:
        candidate.pop("preconditions")
    restored = KernelState.model_validate(saved)
    assert restored.schema_version == saved["schema_version"] == 6
    assert restored.actors["npc"].selected.preconditions == []
    assert all(
        candidate.preconditions == [] for candidate in restored.actors["npc"].proposal.candidates
    )


def test_exact_repeated_character_is_referenced_only_when_it_saves_space():
    turn, value = contract_fixture()
    # Use a long authored description, never a generated summary of it.
    description = ("An independent engineer who values evidence and dry humor. " * 8).strip()
    source = turn.decisions["npc"].candidate_motives["CONTINUE"][0].source
    motive = turn.decisions["npc"].candidate_motives["CONTINUE"][0]
    turn.decisions["npc"].candidate_motives["CONTINUE"][0] = motive.model_copy(
        update={"source": source.model_copy(update={"text": description})}
    )
    original = value.genesis.identity.model_copy(update={"description": description})
    genesis = value.genesis.model_copy(update={"identity": original})
    from backend.engine.chpm.core.reducer import initial
    from backend.engine.chpm.host_state import Mind

    turn.minds["npc"] = Mind(genesis=genesis, snapshot=initial(genesis))
    before = deepcopy(turn.decisions["npc"].model_dump())
    data = runtime.contract_data(turn)["npc"]
    compact = data["selected_motives_not_world_facts"][0]["source"]
    assert compact["text_ref"] == "/authored_identity/character"
    assert "text" not in compact and data["authored_identity"]["character"] == description
    assert json.dumps(data, ensure_ascii=False).count(description) == 1
    assert turn.decisions["npc"].model_dump() == before


def test_maintain_cannot_quietly_drop_a_pending_condition():
    turn, value = contract_fixture()
    chosen = turn.decisions["npc"]
    prior = PreviousIntention(
        selected=chosen.selected,
        scene_id="room",
        source_message_id="reply",
        source_hash="hash",
        spoken_evidence="After the inspection.",
    )
    body = wire_proposal()
    body["choice"] = preferred_choice({"previous_intention": {}})
    body["choice"]["continuity"] = "maintain"
    window = appraisal_context.build(value)
    catalogue = motivation.build(value, [], window)
    raw = Draft.model_validate(body).materialize(catalogue)
    with pytest.raises(ChpmError, match="condition"):
        semantic_choice.select(
            "npc",
            observation(),
            raw.canonical(),
            None,
            raw.choice,
            motivation.resolve(raw, catalogue),
            window,
            prior,
            context_hash="changed",
        )


def test_short_unique_character_text_is_kept_literal_and_full_trace_remains_bound():
    turn, _ = contract_fixture()
    chosen = turn.decisions["npc"]
    before = chosen.model_dump_json()
    data = runtime.contract_data(turn)["npc"]
    source = data["selected_motives_not_world_facts"][0]["source"]
    assert source["text"] == "Independent engineer"
    assert "text_ref" not in source
    assert "provenance_id" not in source
    assert chosen.candidate_motives["CONTINUE"][0].source.provenance_id
    assert chosen.model_dump_json() == before
