"""Narration repair packs rules without trimming source-bound facts or raising limits."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import (
    agent_context,
    inference,
    narration_repair_input,
    rendering,
    roster,
    runtime,
)
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.core.reducer import initial
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.host_state import Mind, record
from backend.engine.chpm.schema import KernelState, Settings
from tests.test_chpm_agenda import undertaking
from tests.test_chpm_compact_contract import contract_fixture
from tests.test_chpm_host_state import mind, source
from tests.test_chpm_kernel import decision, observation
from tests.test_chpm_runtime import manager


def repair_turn(count):
    actors = [f"npc-{index}" for index in range(count)]
    turn = runtime.Turn(
        KernelState(settings=Settings(mode="live" if actors else "off", actor_ids=actors)),
        "input",
        player_request='Can you inspect the compass? "Не выбирай за меня."',
        deferred_names={"inactive": "休息中"},
        reply_character_budget=2048,
    )
    for index in range(count):
        actor = f"npc-{index}"
        text = f'compass {index}: 地図, code {7319 + index}; "check first", not yet verified.'
        value = record(
            mind(actor),
            source(f"old-{index}", text).model_copy(update={"speaker_id": actor}),
            minute=index + 1,
        )
        tools = Tools(value, observation(), {})
        tools.search("compass")
        chosen = decision().model_copy(update={"actor_id": actor})
        chosen.agent_evidence = agent_context.collect(tools.pins, observation())
        chosen.selected.preconditions = ["First inspect the compass"]
        turn.decisions[actor] = chosen
        turn.names[actor] = f"Мира {index}"
        turn.minds[actor] = value
        turn.agendas[actor] = [undertaking(actor, f"agenda-{index}")]
    return turn


@pytest.mark.parametrize("count", [0, 1, 3, 7])
def test_all_source_bound_contract_data_and_original_inputs_survive_packing(count):
    turn = repair_turn(count)
    original_system = 'Original language, cast and agency policy.\n{"id":"unchanged"}'
    rejected = 'Мира: "Нет… сначала проверю."\nPreserve this unrelated sentence.'
    resolution = 'Host outcome: compass still locked; player has not moved.\n"unchanged"'
    issues = ["Missing conditional intention", "Keep the existing speaker identity"]
    reminder = 'Portrait policy; cast: {"npc-0":"Мира 0","inactive":"休息中"}'
    expected = runtime.contract_data(turn)
    before = {actor: value.model_dump() for actor, value in turn.minds.items()}

    system, payload = narration_repair_input.build(
        turn, original_system, rejected, resolution, issues, portrait_reminder=reminder
    )

    assert system.startswith(original_system + "\n")
    assert system.endswith("\n" + reminder)
    assert roster.instruction(turn.deferred_names) in system
    assert "2048 characters" in system
    assert json.loads(payload) == {
        "player_request": turn.player_request,
        "host_resolution": resolution,
        "narration": rejected,
        "issues": issues,
        "dialogue_contract": expected,
    }
    # The complete typed block survives as the same compact JSON, including text refs.
    assert json.dumps(expected, ensure_ascii=False, separators=(",", ":")) in payload
    for actor, row in json.loads(payload)["dialogue_contract"].items():
        index = int(actor.removeprefix("npc-"))
        evidence = row["agent_observed_sources"]
        assert len(evidence) == 1
        assert evidence[0]["source_message_id"] == f"old-{index}"
        assert evidence[0]["text"] == turn.decisions[actor].agent_evidence[0].text
        assert row["preconditions"] == ["First inspect the compass"]
        assert len(row["ongoing_agenda_not_world_facts"]) == 1
    assert {actor: value.model_dump() for actor, value in turn.minds.items()} == before


def test_repair_preserves_the_same_actor_relative_motive_reference_and_grounding():
    turn, value = contract_fixture()
    description = (
        "An independent engineer who verifies the evidence before agreeing. " * 3
    ).strip()
    genesis = value.genesis.model_copy(
        update={"identity": value.genesis.identity.model_copy(update={"description": description})}
    )
    turn.minds["npc"] = Mind(genesis=genesis, snapshot=initial(genesis))
    chosen = turn.decisions["npc"]
    original_motive = chosen.candidate_motives["CONTINUE"][0]
    chosen.candidate_motives["CONTINUE"][0] = original_motive.model_copy(
        update={"source": original_motive.source.model_copy(update={"text": description})}
    )
    expected = runtime.contract_data(turn)
    assert expected["npc"]["selected_motives_not_world_facts"][0]["source"]["text_ref"] == (
        "/authored_identity/character"
    )

    _, payload = narration_repair_input.build(
        turn,
        "Original policy",
        "Rejected reply",
        "No completed inspection",
        [],
        portrait_reminder="",
    )

    supplied = json.loads(payload)["dialogue_contract"]
    assert supplied == expected
    reference = supplied["npc"]["selected_motives_not_world_facts"][0]["source"]["text_ref"]
    assert reference == "/authored_identity/character"
    assert supplied["npc"]["authored_identity"]["character"] == description
    assert supplied["npc"]["preconditions"] == ["The inspection is confirmed."]


def test_existing_full_contract_is_retained_once_with_an_explicit_reference():
    turn = repair_turn(3)
    existing = runtime.contract(turn)
    original_system = "Narration policy\n" + existing + "\nRest of original system"

    system, payload = narration_repair_input.build(
        turn,
        original_system,
        "Rejected narration",
        "Host resolution",
        ["Repair the chosen response"],
        portrait_reminder="Portrait policy",
    )

    assert system.startswith(original_system + "\n")
    assert system.count(existing) == 1
    assert len(system) - len(original_system) < 1000
    body = json.loads(payload)
    assert body["dialogue_contract_source"] == "original_system"
    assert "dialogue_contract" not in body
    for actor, data in runtime.contract_data(turn).items():
        assert json.dumps(data, ensure_ascii=False, separators=(",", ":")) in system
        assert actor in existing


@pytest.mark.parametrize("overflow", [0, 1])
@pytest.mark.parametrize("embedded", [False, True])
async def test_real_repair_checks_the_exact_limit_before_dispatch_without_truncation(
    monkeypatch, overflow, embedded
):
    host, _ = manager()
    turn = repair_turn(1)
    reminder = 'Portrait policy, exact IDs: {"npc-0":"Мира 0"}'
    monkeypatch.setattr(rendering, "output_reminder", lambda _: reminder)
    model = SimpleNamespace(
        enable_thinking=True,
        max_tokens=8192,
        model="mock",
        request_timeout=10,
        aexecute_simple_task=AsyncMock(return_value='Мира 0: "Сначала проверю."'),
    )
    selected = []

    def model_for(_host, role, _router):
        selected.append(role)
        return model

    monkeypatch.setattr(inference, "model_for", model_for)
    original = "Complete original system, including cast and language.\n"
    if embedded:
        original += runtime.contract(turn) + "\n"
    args = ("The rejected text stays exact…", "Locked. Player stayed.", ["Repair only stance"])
    baseline, payload = narration_repair_input.build(
        turn, original, *args, portrait_reminder=reminder
    )
    padding = turn.initial.settings.max_input_chars - len(baseline) - len(payload) + overflow
    assert padding > 0
    original += "x" * padding
    expected_system, expected_payload = narration_repair_input.build(
        turn, original, *args, portrait_reminder=reminder
    )
    assert len(expected_system) + len(expected_payload) == 24000 + overflow

    if overflow:
        with pytest.raises(RecoverableChpmError, match="24001 > 24000"):
            await rendering._repair(host, turn, *args, original)
        assert selected == []
        model.aexecute_simple_task.assert_not_awaited()
        assert turn.usage.calls == 0 and turn.usage.repairs == 0
    else:
        result = await rendering._repair(host, turn, *args, original)
        assert result == 'Мира 0: "Сначала проверю."'
        assert selected == ["complex"]
        call = model.aexecute_simple_task.await_args
        assert call.args[:2] == (expected_system, expected_payload)
        assert call.args[0].startswith(original + "\n")
        assert turn.usage.calls == 1 and turn.usage.repairs == 1
        assert turn.usage.input_chars == 24000
