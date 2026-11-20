"""Real native/JSON compatibility ports stage choices for the existing RPG owner."""

import json
from copy import deepcopy

import pytest

from backend.core.llm_tool_turn import InvalidToolTurnError, ToolCall, ToolTurn
from backend.engine.chpm.errors import InferenceUnavailableError, RecoverableChpmError
from backend.engine.chpm.inference import OutputBudgetError
from backend.engine.chpm.schema import Settings, Usage
from backend.engine.gameplay.combat.ability_choices import prepare
from backend.engine.npc_actions.rpg_port import definitions, make_selector
from backend.engine.turn_replay.commands import prepare_command
from backend.models.turn_replay import TurnReplay
from tests.combat_boundary_support import combat_world, deterministic_randint, enemy_combat
from tests.test_npc_ability_choices import ability

__all__ = ["combat_world"]


def call(name="use_ability", arguments=None, identifier="call_1"):
    raw = json.dumps(
        {"ability_id": "SPARK", "target_id": "PLAYER"} if arguments is None else arguments
    )
    return ToolCall(identifier, name, raw)


def turn(*calls, reason="tool_calls"):
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": item.id,
                "type": "function",
                "function": {"name": item.name, "arguments": item.arguments_raw},
            }
            for item in calls
        ],
    }
    return ToolTurn(message, tuple(calls), reason)


class ScriptModel:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.max_tokens, self.enable_thinking, self.request_timeout = 1200, True, 15
        self.model = "offline-model"

    def next(self, data):
        self.calls.append(deepcopy(data))
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    async def aexecute_tool_turn(self, messages, tools, _model, **_kwargs):
        return self.next((messages, tools))

    async def aexecute_simple_task(self, system, payload, _model, **_kwargs):
        reply = self.next((system, json.loads(payload)))
        if isinstance(reply, str):
            return reply
        return json.dumps(
            {
                "requests": [
                    {"name": item.name, "arguments": json.loads(item.arguments_raw)}
                    for item in reply.calls
                ]
            }
        )


def settings(protocol="native", **changes):
    return Settings(
        control_scope="combat_actions",
        mode="live",
        workflow="integrated",
        actor_ids=["GUARD"],
        action_tools=True,
        agent_steps=3,
        tool_protocol=protocol,
        **{"max_calls_per_turn": 9, **changes},
    )


async def bound(world, model, protocol="native", *, usage=None, configured=None):
    combat = await enemy_combat(world, action=ability())
    await prepare_command(world.manager, "/attack GUARD")
    world.manager._chpm_model_factory = lambda _role: model
    selector = make_selector(world.manager, configured or settings(protocol), usage=usage)
    world.manager.npc_ability_selector = selector
    world.manager.npc_ability_actor_ids = {"GUARD"}
    return combat, selector


@pytest.mark.parametrize("profile", ["auto", "gemma", "qwen"])
@pytest.mark.parametrize("protocol", ["auto", "native", "json"])
async def test_model_selection_executes_once_through_existing_owner(
    combat_world, monkeypatch, protocol, profile
):
    world = combat_world
    model = ScriptModel(turn(call()))
    usage = Usage()
    combat, _selector = await bound(
        world, model, protocol, usage=usage, configured=settings(protocol, tool_profile=profile)
    )
    monkeypatch.setattr(
        "backend.engine.combat.special_attacks.random.randint", deterministic_randint
    )
    _ = [chunk async for chunk in world.manager.combat._advance_until_player(combat, False)]
    assert len(model.calls) == usage.calls == 1
    portable = protocol == "json" or (protocol == "auto" and profile in {"gemma", "qwen"})
    assert isinstance(model.calls[0][0], str) is portable
    assert world.avatar.hp == 99 and combat["enemies"][0]["mana"] == 93
    assert combat["turn_index"] == 1 and combat["turn"] == "player"
    recovery = await world.db.get(TurnReplay, world.game.id)
    assert recovery.status == "executing" and recovery.before["avatar"]["hp"] == 100


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_wrong_id_gets_correlated_feedback_then_corrects(combat_world, protocol):
    model = ScriptModel(
        turn(call(arguments={"ability_id": "missing", "target_id": "PLAYER"})),
        turn(call(identifier="call_2")),
    )
    usage = Usage()
    combat, selector = await bound(combat_world, model, protocol, usage=usage)
    selected = await selector(await prepare(combat_world.manager.combat, combat, "GUARD"))
    assert selected.ability_id == "SPARK" and usage.calls == 2
    if protocol == "native":
        messages = model.calls[1][0]
        result = next(row for row in messages if row["role"] == "tool")
        assert result["tool_call_id"] == "call_1" and result["name"] == "use_ability"
        feedback = json.loads(result["content"])
    else:
        history = model.calls[1][1]["previous_lookups"][0]
        assert history["requests"][0]["tool"] == "use_ability"
        feedback = history["results"][0]
    assert feedback["world_changed"] is False and "exact ID" in feedback["message"]
    assert combat_world.avatar.hp == 100 and combat["enemies"][0]["mana"] == 100


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_keep_default_requires_an_explicit_call(combat_world, protocol):
    model = ScriptModel(turn(), turn(call("keep_default", {}, "call_2")))
    combat, selector = await bound(combat_world, model, protocol)
    assert await selector(await prepare(combat_world.manager.combat, combat, "GUARD")) is None
    assert len(model.calls) == 2 and combat_world.avatar.hp == 100


@pytest.mark.parametrize(
    "arguments",
    [
        {"ability_id": "SPARK", "target_id": "GUARD"},
        {"ability_id": "SPARK", "target_id": "PLAYER", "actor_id": "OTHER"},
        {"ability_id": "SPARK", "target_id": "PLAYER", "effects": []},
        {"ability_id": "SPARK"},
        {"ability_id": 7, "target_id": "PLAYER"},
    ],
)
async def test_bad_arguments_never_change_world_and_can_be_corrected(combat_world, arguments):
    model = ScriptModel(turn(call(arguments=arguments)), turn(call("keep_default", {}, "call_2")))
    combat, selector = await bound(combat_world, model)
    assert await selector(await prepare(combat_world.manager.combat, combat, "GUARD")) is None
    assert combat_world.avatar.hp == 100 and combat["enemies"][0]["mana"] == 100


async def test_ambiguous_batch_is_rejected_as_a_whole(combat_world):
    model = ScriptModel(
        turn(call(), call("keep_default", {}, "call_2")), turn(call(identifier="call_3"))
    )
    combat, selector = await bound(combat_world, model)
    assert (
        await selector(await prepare(combat_world.manager.combat, combat, "GUARD"))
    ).ability_id == "SPARK"
    assert len(model.calls) == 2 and combat_world.avatar.hp == 100


async def test_no_unavailable_ability_is_offered(combat_world):
    model = ScriptModel(turn(call()), turn(call("keep_default", {}, "call_2")))
    combat, selector = await bound(combat_world, model)
    combat["enemies"][0]["mana"] = 1
    current = await prepare(combat_world.manager.combat, combat, "GUARD")
    assert [row["function"]["name"] for row in definitions(current.context)] == ["keep_default"]
    assert await selector(current) is None
    assert combat["enemies"][0]["mana"] == 1


async def test_three_bad_rounds_do_not_silently_choose_default(combat_world):
    model = ScriptModel(*(turn(call("made_up", {}, f"call_{index}")) for index in range(3)))
    combat, _selector = await bound(combat_world, model)
    with pytest.raises(RecoverableChpmError, match="rounds exhausted"):
        _ = [
            chunk
            async for chunk in combat_world.manager.combat._advance_until_player(combat, False)
        ]
    assert len(model.calls) == 3 and combat["turn_index"] == 0
    assert combat_world.avatar.hp == 100 and combat["enemies"][0]["mana"] == 100


@pytest.mark.parametrize(
    "reply,error",
    [
        (TimeoutError(), InferenceUnavailableError),
        (turn(call(), reason="length"), OutputBudgetError),
        (turn(call(), reason="content_filter"), RecoverableChpmError),
    ],
)
async def test_transport_or_truncation_never_sends_an_uncertain_retry(combat_world, reply, error):
    model = ScriptModel(reply, turn(call()))
    combat, selector = await bound(combat_world, model)
    with pytest.raises(error):
        await selector(await prepare(combat_world.manager.combat, combat, "GUARD"))
    assert len(model.calls) == 1 and combat_world.avatar.hp == 100


@pytest.mark.parametrize(
    "protocol,reply",
    [
        ("native", InvalidToolTurnError("Invalid arguments", code="invalid_structure")),
        ("json", '{"requests":['),
    ],
)
async def test_completed_bad_envelope_can_correct_within_existing_rounds(
    combat_world, protocol, reply
):
    model = ScriptModel(reply, turn(call(identifier="call_2")))
    combat, selector = await bound(combat_world, model, protocol)
    assert (
        await selector(await prepare(combat_world.manager.combat, combat, "GUARD"))
    ).ability_id == "SPARK"
    assert len(model.calls) == 2


async def test_one_frame_cannot_trigger_second_model_selection(combat_world):
    model = ScriptModel(turn(call()))
    combat, selector = await bound(combat_world, model)
    current = await prepare(combat_world.manager.combat, combat, "GUARD")
    await selector(current)
    with pytest.raises(RecoverableChpmError, match="already been used"):
        await selector(current)
    assert len(model.calls) == 1


async def test_stale_recovery_flags_cannot_replace_actual_durable_backup(combat_world):
    world = combat_world
    model = ScriptModel(turn(call()))
    combat, selector = await bound(world, model)
    recovery = await world.db.get(TurnReplay, world.game.id)
    recovery.status, recovery.backup = "command_complete", None
    await world.db.commit()
    current = await prepare(world.manager.combat, combat, "GUARD")
    with pytest.raises(RecoverableChpmError, match="durable current turn backup"):
        await selector(current)
    assert not model.calls and world.avatar.hp == 100


async def test_shared_command_budget_applies_across_selection_frames(combat_world):
    model = ScriptModel(turn(call()), turn(call(identifier="call_2")))
    usage = Usage(calls=8)
    combat, selector = await bound(
        combat_world, model, usage=usage, configured=settings(max_calls_per_turn=9)
    )
    await selector(await prepare(combat_world.manager.combat, combat, "GUARD"))
    combat["round"] = 2
    with pytest.raises(RecoverableChpmError, match="budget exhausted"):
        await selector(await prepare(combat_world.manager.combat, combat, "GUARD"))
    assert len(model.calls) == 1 and usage.calls == 9


@pytest.mark.parametrize("violation", ["recovery", "scope", "vn", "actor"])
async def test_no_model_request_without_bound_mode_actor_and_recovery(combat_world, violation):
    model = ScriptModel(turn(call()))
    combat, selector = await bound(combat_world, model)
    current = await prepare(combat_world.manager.combat, combat, "GUARD")
    if violation == "recovery":
        combat_world.manager._recoverable_turn = False
    if violation == "scope":
        selector = make_selector(
            combat_world.manager, settings().model_copy(update={"control_scope": "dialogue"})
        )
    if violation == "vn":
        combat_world.manager.adventure.rule_enforcement_mode = "vn"
    if violation == "actor":
        selector = make_selector(
            combat_world.manager, settings().model_copy(update={"actor_ids": ["OTHER"]})
        )
    with pytest.raises(RecoverableChpmError):
        await selector(current)
    assert not model.calls and combat_world.avatar.hp == 100


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_only_bound_authored_identity_is_included_in_model_context(combat_world, protocol):
    world = combat_world
    world.npc.goal = "Protect the workshop."
    world.npc.character = "A patient keeper who resists needless harm."
    world.npc.description = "A guard in blue." * 200
    world.npc.metadata_json = {
        **world.npc.metadata_json,
        "personality_profile": {"conflict": "negotiate", "risk": "invented"},
        "private_other_mind": "OTHER_PRIVATE_MARKER",
    }
    model = ScriptModel(turn(call("keep_default", {})))
    combat, selector = await bound(world, model, protocol)
    await selector(await prepare(world.manager.combat, combat, "GUARD"))
    payload = (
        json.loads(model.calls[0][0][1]["content"]) if protocol == "native" else model.calls[0][1]
    )
    identity = payload["own_authored_identity"]
    assert identity["goal"] == world.npc.goal and identity["character"] == world.npc.character
    assert "workable agreements" in identity["personality"]
    assert len(identity["description"]) == 400
    assert "invented" not in str(identity) and "OTHER_PRIVATE_MARKER" not in str(payload)
    assert "inventory" not in payload and "TOKEN" not in str(payload)
