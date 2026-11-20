"""World-command tool envelopes share strict native/JSON parsing without scope authority."""

import json
from dataclasses import replace

import pytest
from jsonschema import Draft202012Validator

from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.native_tool_contracts import NativeToolArgumentError, parse_call
from backend.engine.chpm.offered_tools import definitions
from backend.engine.npc_actions.contracts import ACTION_MODELS, Take
from backend.engine.npc_actions.preview import Draft
from backend.engine.npc_actions.tool_schema import definitions as action_definitions
from tests.observable_state_support import tools_for, world
from tests.test_npc_action_previews import fixture


def test_action_schemas_are_closed_and_never_accept_model_actor_or_session_authority():
    tools = action_definitions(set(ACTION_MODELS))
    assert {row["function"]["name"] for row in tools} == set(ACTION_MODELS)
    for row in tools:
        schema = row["function"]["parameters"]
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert not {"tool", "actor_id", "session_id", "proof"} & schema["properties"].keys()


@pytest.mark.parametrize(
    "extra",
    [
        {"actor_id": "other"},
        {"session_id": "other"},
        {"tool": "give_item"},
        {"proof": {}},
        {"complete": True},
    ],
)
def test_extra_authority_or_completion_fields_are_rejected(extra):
    with pytest.raises(NativeToolArgumentError):
        parse_call("take_item", json.dumps({"item_id": "KEY", **extra}))


@pytest.mark.parametrize(
    "raw",
    [
        '{"item_id":true}',
        '{"item_id":"KEY","item_id":"OTHER"}',
        '{"item_id":null}',
        '{"item_id":5}',
        "{}",
        '{"item_id":""}',
        '{"item_id":"KEY","number":NaN}',
    ],
)
def test_childlike_malformed_arguments_never_produce_an_executable_command(raw):
    with pytest.raises(NativeToolArgumentError):
        parse_call("take_item", raw)


def test_disabled_action_tools_cannot_stage_even_a_known_well_formed_request():
    tools = tools_for(*world())
    assert isinstance(tools, Tools)
    names = {row["function"]["name"] for row in definitions(tools)}
    assert not names & set(ACTION_MODELS)
    assert tools.execute(parse_call("take_item", '{"item_id":"KEY"}')) == {
        "status": "unavailable_actions"
    }


def test_enabled_action_tool_only_stages_and_uses_the_bound_npc():
    host, scope, draft = fixture()
    tools = tools_for(*world())
    tools.actions = draft
    request = parse_call("take_item", '{"item_id":"KEY"}')
    assert isinstance(request, Take)
    result = tools.execute(request)
    assert result["status"] == "staged" and result["world_changed"] is False
    assert scope.possessions.owners["KEY"] == "__scene__"
    assert "KEY" not in [
        row.get("id") for row in scope.actors["npc"]["inventory"] if isinstance(row, dict)
    ]


@pytest.mark.parametrize(
    "changes",
    [{"actor_id": "other"}, {"session_id": "other"}, {"input_id": "other"}, {"scene_id": "other"}],
)
def test_a_misbound_action_draft_cannot_act_for_a_different_observer_input_or_scene(changes):
    _, scope, _ = fixture()
    tools = tools_for(*world())
    tools.actions = Draft(replace(scope, **changes))
    result = tools.execute(Take(tool="take_item", item_id="KEY"))
    assert result["status"] == "unavailable_actions"
    assert tools.actions.requests == []
