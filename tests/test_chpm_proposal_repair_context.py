"""A single proposal repair receives the rejected object and all available choice diagnostics."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, Field

from backend.engine.chpm import cognitive_context, motivation, proposal_attempt, semantic_choice
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.json_contract import response_schema
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import Decision, Settings, Usage
from backend.engine.chpm.state import KEY, load
from tests.conftest import TestSessionLocal
from tests.test_chpm_kernel import observation, wire_proposal
from tests.test_chpm_reliability import Replies, Response
from tests.test_chpm_semantic_choice import fixture
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import ACTION, install_roles, seed_vn


def test_wire_choice_uses_distinct_ids_from_the_same_motivation_catalogue():
    mind, _, _, _ = fixture()
    _, catalogue, _, identifiers = cognitive_context.pack(
        mind,
        observation(),
        {"authored_character": mind.genesis.identity.description},
        [],
        Settings(),
        "Use the schema.",
        wire_schema=Draft,
    )
    assert identifiers["motive_ids"] == list(catalogue.sources)
    contract = response_schema(Draft, identifiers)
    ids = contract["$defs"]["ChoicePreference"]["properties"]["motive_ids"]
    assert ids["items"]["enum"] == list(catalogue.sources)
    assert ids["uniqueItems"] is True
    assert ids["minItems"] == 1 and ids["maxItems"] == 3


def test_compact_identifier_schema_preserves_the_fields_own_meaning():
    class ActorReference(BaseModel):
        actor_id: str = Field(description="The observer who personally witnessed this source.")

    contract = response_schema(ActorReference, {"actor_id": ["npc"]})
    field = contract["properties"]["actor_id"]
    assert field["enum"] == ["npc"]
    assert field["description"] == "The observer who personally witnessed this source."


def accept_choice(draft):
    mind, window, _, _ = fixture()
    catalogue = motivation.build(mind, [], window)
    raw = draft.materialize(catalogue)
    return semantic_choice.select(
        "npc",
        observation(),
        raw.canonical(),
        raw.question_gate,
        raw.choice,
        motivation.resolve(raw, catalogue),
        window,
        None,
        context_hash="same-context",
    )


async def test_overlong_reason_and_wrong_motives_share_one_repair_without_rebuilding_context():
    original = wire_proposal()
    original["choice"]["reason"] = "я" * 301
    original["choice"]["motive_ids"] = ["invented-motive"]
    corrected = deepcopy(original)
    corrected["choice"].update(reason="Preserve the established purpose.", motive_ids=["goal1"])
    model = Replies([json.dumps(original), json.dumps(corrected)])
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    usage = Usage()
    context = {"authored_character": "Pinned original identity", "observation": "Current facts"}

    decision = await proposal_attempt.request(
        manager,
        Settings(mode="live", actor_ids=["npc"], max_calls_per_turn=6),
        usage,
        "Use the schema.",
        context,
        Draft,
        {},
        accept_choice,
    )

    feedback = model.requests[1][2]["proposal_feedback"]
    assert "300" in feedback["error"]
    assert "invented-motive" in feedback["error"]
    assert "goal1" in feedback["error"]
    assert feedback["rejected_proposal"] == original
    assert all(model.requests[1][2][key] == value for key, value in context.items())
    assert usage.calls == 2 and usage.proposal_repairs == 1
    assert decision.choice_preference.reason == corrected["choice"]["reason"]
    assert decision.choice_preference.motive_ids == ["goal1"]
    assert Decision.model_validate_json(decision.model_dump_json()) == decision


async def test_semantically_rejected_choice_is_returned_with_exact_allowed_motives():
    original = wire_proposal()
    original["choice"]["motive_ids"] = ["character"]
    corrected = deepcopy(original)
    corrected["choice"]["motive_ids"] = ["goal1"]
    model = Replies([json.dumps(original), json.dumps(corrected)])
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    usage = Usage()
    await proposal_attempt.request(
        manager,
        Settings(mode="live", actor_ids=["npc"]),
        usage,
        "Use the schema.",
        {},
        Draft,
        {},
        accept_choice,
    )
    feedback = model.requests[1][2]["proposal_feedback"]
    assert "CONTINUE" in feedback["error"] and "goal1" in feedback["error"]
    assert feedback["rejected_proposal"]["choice"]["motive_ids"] == ["character"]


async def test_invalid_json_is_not_fed_back_as_an_ambiguous_candidate():
    model = Replies(['{"value":', '{"value":"valid"}'])
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    await proposal_attempt.request(
        manager,
        Settings(mode="live", actor_ids=["npc"]),
        Usage(),
        "Use the schema.",
        {},
        Response,
        {},
        lambda v: v,
    )
    assert "rejected_proposal" not in model.requests[1][2]["proposal_feedback"]


async def test_large_rejected_response_does_not_displace_required_context_or_expand_budget():
    model = Replies([json.dumps({"value": "x" * 15000}), '{"value":"valid"}'])
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    context = {"pinned_context": "y" * 6000}
    settings = Settings(mode="live", actor_ids=["npc"], max_input_chars=16000)
    await proposal_attempt.request(
        manager,
        settings,
        Usage(),
        "Use the schema.",
        context,
        Response,
        {},
        lambda v: v,
    )
    _, prompt, payload = model.requests[1]
    assert payload["pinned_context"] == context["pinned_context"]
    feedback = payload["proposal_feedback"]
    assert "rejected_proposal" not in feedback
    assert "input budget" in feedback["rejected_proposal_omitted"]
    assert (
        len(prompt) + len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) <= 16000
    )


async def test_repeated_invalid_choice_remains_rejected_after_the_single_reserved_retry():
    original = wire_proposal()
    original["choice"]["motive_ids"] = ["goal1", "goal1"]
    model = Replies([json.dumps(original), json.dumps(original)])
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    usage = Usage()
    with pytest.raises(RecoverableChpmError, match="remains invalid"):
        await proposal_attempt.request(
            manager,
            Settings(mode="live", actor_ids=["npc"]),
            usage,
            "Use the schema.",
            {},
            Draft,
            {},
            accept_choice,
        )
    assert usage.calls == 2 and usage.proposal_repairs == 1
    assert "Duplicate" in usage.proposal_feedback[-1]


@pytest.mark.parametrize("length", [299, 300])
def test_choice_reason_boundary_round_trips_without_truncation(length):
    original = wire_proposal()
    original["choice"]["reason"] = "я" * length
    decision = accept_choice(Draft.model_validate(original))
    assert decision.choice_preference.reason == original["choice"]["reason"]
    assert Decision.model_validate_json(decision.model_dump_json()) == decision


async def test_real_turn_commits_only_the_corrected_choice_and_closes_the_gap(monkeypatch):
    from backend.engine.chpm import inference, rendering
    from backend.engine.chpm.schema import KernelState
    from backend.engine.gameplay.manager import GameTurnManager

    class RepairingRoles(ChpmRoles):
        async def simple(self, system, payload, model, **kwargs):
            phase = kwargs.get("phase")
            if phase == "proposal_repair":
                self.chpm_calls.append(phase)
                feedback = json.loads(payload)["proposal_feedback"]
                assert "300" in feedback["error"] and "uncited" in feedback["error"]
                draft = deepcopy(feedback["rejected_proposal"])
                preferred = draft["choice"]["preferred"]
                draft["choice"].update(
                    reason="Advance my established purpose.",
                    motive_ids=[draft["candidates"][preferred]["motives"][0]["motive_id"]],
                )
                return json.dumps(draft)
            response = await super().simple(system, payload, model, **kwargs)
            if phase == "proposal":
                draft = json.loads(response)
                draft["choice"].update(reason="x" * 301, motive_ids=["uncited"])
                return json.dumps(draft)
            return response

    roles = RepairingRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        before = KernelState(
            settings=Settings(mode="live", actor_ids=["LINA"], failure_policy="strict")
        )
        before.recovery.pending_gap_turns = 25
        state.entity_states = {**state.entity_states, KEY: before.model_dump()}
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        events = [event async for event in manager.process_turn(ACTION)]
        assert not any(event.startswith("event: error") for event in events), "".join(events)
        assert any(event.startswith("event: final") for event in events)
        await db.refresh(state)
        saved = load(state)
        assert saved.actors["LINA"].status == "delivered"
        assert saved.actors["LINA"].choice_preference.reason == "Advance my established purpose."
        assert saved.usage.calls == 4 and saved.usage.proposal_repairs == 1
        assert saved.recovery.pending_gap_turns == 0
        assert "rejected_proposal" not in json.dumps(saved.model_dump())
        assert KernelState.model_validate_json(saved.model_dump_json()) == saved
    assert roles.chpm_calls == ["perception", "proposal", "proposal_repair", "validation"]
