"""Earlier resolution stays visible but cannot erase later command-owned facts."""

import json
from copy import deepcopy

import pytest

from backend.engine.chpm import (
    continuation,
    inference,
    narration_repair_input,
    passages,
    rendering,
    runtime,
)
from backend.engine.npc_actions import instructions
from tests.npc_control_support import bind_turn
from tests.test_chpm_runtime import prepared

RESOLUTION = (
    "The attempted item change did not occur; possessions remain unchanged. "
    "Unknown or unavailable item. An unrelated locked door stayed locked."
)
TEXT = 'Rin: "Here is the key."'
OUTCOMES = {
    "npc": [
        {
            "index": 0,
            "tool": "take_item",
            "status": "applied",
            "effect": {"item_id": "KEY", "source_owner": "__scene__", "destination_owner": "npc"},
        },
        {
            "index": 1,
            "tool": "give_item",
            "status": "applied",
            "effect": {"item_id": "KEY", "source_owner": "npc", "destination_owner": "__player__"},
        },
    ]
}
WITHHELD_OUTCOMES = {
    "npc": [
        {
            "index": index,
            "tool": tool,
            "status": "applied",
            "effect": {},
            "effect_omitted": {
                "fields": ["destination_owner", "item_id", "source_owner"],
                "reason": "public_view_unavailable",
            },
        }
        for index, tool in enumerate(("take_item", "give_item"))
    ]
}


def command_turn(outcomes=OUTCOMES):
    manager = prepared()
    turn = manager._chpm_turn
    turn.action_outcomes = deepcopy(outcomes)
    bind_turn(manager, turn)
    turn._control_host = manager
    return turn


def effects(outcomes):
    return {
        actor: [
            {
                key: value
                for key, value in row.items()
                if key in {"index", "tool", "status", "effect", "effect_omitted"}
            }
            for row in rows
        ]
        for actor, rows in outcomes.items()
    }


def test_original_narrator_marks_resolution_and_withholds_unobserved_receipt_details():
    turn = command_turn()
    data = runtime.contract_data(turn)
    assert "before_command_publication" in data["npc"]["observation_time"]
    assert "host resolution" in data["npc"]["observation_time"]
    assert effects({"npc": data["npc"]["authoritative_command_outcomes"]}) == WITHHELD_OUTCOMES
    assert instructions.NARRATION in runtime.contract(turn)
    assert instructions.RESOLUTION_CHRONOLOGY in runtime.contract(turn)
    assert effects(turn.action_outcomes) == OUTCOMES


async def test_actual_review_request_and_preflight_use_the_same_owner_chronology(monkeypatch):
    turn = command_turn()
    seen, calculated = [], []
    compose = inference.compose

    def composed(instruction, *args, **kwargs):
        calculated.append(instruction)
        return compose(instruction, *args, **kwargs)

    async def request(_manager, _settings, _usage, instruction, payload, *_args, **_kwargs):
        seen.append((instruction, payload))
        assert payload["host_resolution"] == RESOLUTION
        assert payload["host_resolution_time"] == "before_command_publication"
        assert (
            effects({"npc": payload["contract"]["npc"]["authoritative_command_outcomes"]})
            == WITHHELD_OUTCOMES
        )
        assert instructions.RESOLUTION_CHRONOLOGY in instruction
        assert instructions.NARRATION in instruction
        assert instruction.count(instructions.EXECUTION) == 1
        return passages.Review(
            matches=True,
            evidence=[{"actor_id": "npc", "passage_id": next(iter(payload["passages"]))}],
        )

    monkeypatch.setattr(inference, "compose", composed)
    monkeypatch.setattr(inference, "request", request)
    assert rendering._review_room(turn) > 0
    verdict = await rendering._review(turn._control_host, turn, TEXT, RESOLUTION)
    assert verdict.matches and len(seen) == 1
    assert calculated == [seen[0][0]]
    assert effects(turn.action_outcomes) == OUTCOMES


@pytest.mark.parametrize("embedded", [False, True])
def test_repair_retains_exact_earlier_failure_and_marks_its_time_in_both_paths(embedded):
    turn = command_turn()
    original = runtime.contract(turn) if embedded else "Original narration policy."
    system, content = narration_repair_input.build(
        turn, original, TEXT, RESOLUTION, ["Review the command chronology"], portrait_reminder=""
    )
    payload = json.loads(content)
    assert payload["host_resolution"] == RESOLUTION
    assert payload["host_resolution_time"] == "before_command_publication"
    assert system.count(instructions.RESOLUTION_CHRONOLOGY) == 1
    if not embedded:
        assert (
            effects({"npc": payload["dialogue_contract"]["npc"]["authoritative_command_outcomes"]})
            == WITHHELD_OUTCOMES
        )
    assert effects(turn.action_outcomes) == OUTCOMES


@pytest.mark.parametrize(
    "status", ["attempted", "blocked", "stale", "skipped_dependency", "unconfirmed"]
)
def test_chronology_does_not_promote_unsuccessful_or_unresolved_outcomes(status):
    outcomes = {"npc": [{"index": 0, "tool": "give_item", "status": status}]}
    turn = command_turn(outcomes)
    data = runtime.contract_data(turn)
    assert effects({"npc": data["npc"]["authoritative_command_outcomes"]}) == outcomes
    assert "before_command_publication" in data["npc"]["observation_time"]
    assert "Only status=applied" in instructions.RESOLUTION_CHRONOLOGY
    assert "unrelated" in instructions.RESOLUTION_CHRONOLOGY
    assert effects(turn.action_outcomes) == outcomes


def test_ordinary_fallback_keeps_the_same_chronology_after_decisions_are_discarded():
    turn = command_turn()
    continuation.activate(turn, "review_unavailable")
    text = continuation.contract(turn)
    assert '"host_resolution_time":"before_command_publication"' in text
    assert instructions.NARRATION in text
    assert effects(turn.action_outcomes) == OUTCOMES and not turn.decisions


def test_no_command_result_adds_neither_chronology_claim_nor_command_instructions():
    turn = command_turn({})
    assert "host_resolution_time" not in rendering._review_payload(turn, {}, RESOLUTION)
    assert instructions.NARRATION not in runtime.contract(turn)
    system, content = narration_repair_input.build(
        turn, "Original policy", TEXT, RESOLUTION, ["Keep the original facts"], portrait_reminder=""
    )
    assert "host_resolution_time" not in json.loads(content)
    assert instructions.NARRATION not in system


def test_explicit_empty_publication_reaches_review_and_repair_without_completed_effects():
    turn = command_turn({"npc": []})
    payload = rendering._review_payload(turn, {}, RESOLUTION)
    assert payload["host_resolution"] == RESOLUTION
    assert payload["host_resolution_time"] == "before_command_publication"
    assert payload["contract"]["npc"]["authoritative_command_outcomes"] == []
    assert instructions.EXECUTION in runtime.contract(turn)
    system, content = narration_repair_input.build(
        turn, "Original policy", TEXT, RESOLUTION, ["Keep the original facts"], portrait_reminder=""
    )
    repair = json.loads(content)
    assert repair["host_resolution_time"] == "before_command_publication"
    assert repair["dialogue_contract"]["npc"]["authoritative_command_outcomes"] == []
    assert instructions.EXECUTION in system
    assert turn.action_outcomes == {"npc": []}
