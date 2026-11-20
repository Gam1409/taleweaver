"""Selected family policies reuse the existing bounded native and portable ports."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.core.llm_tool_turn import NativeToolsUnsupportedError
from backend.engine.chpm import agent, agent_native, inference, parallel_budget
from backend.engine.chpm.errors import InferenceUnavailableError, RecoverableChpmError
from backend.engine.chpm.host_state import record
from backend.engine.chpm.json_tool_port import JsonToolPort
from backend.engine.chpm.native_tool_contracts import tool_definitions
from backend.engine.chpm.notebook import NotebookWorkspace
from backend.engine.chpm.notebook_tools import NotebookDraft
from backend.engine.chpm.schema import Settings, Usage
from tests.test_chpm_host_state import mind, source
from tests.test_chpm_kernel import observation
from tests.test_chpm_native_notebook_loop import NativeModel, call, turn
from tests.test_chpm_reliability import Replies

PROFILES = ("auto", "anthropic", "openai", "mistral", "gemma", "deepseek", "qwen")
PORTABLE_PROFILES = {"gemma", "qwen"}


def host(model):
    return SimpleNamespace(game_id="session", _chpm_model_factory=lambda _role: model)


def definition(schema):
    return [{"type": "function", "function": {"name": "inspect_schema", "parameters": schema}}]


def parameters(value):
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"value": value},
        "required": ["value"],
    }


class PortableReplies(NativeModel):
    def __init__(self, replies):
        super().__init__([])
        self.replies = iter(replies)

    async def aexecute_simple_task(self, system, content, model, **kwargs):
        self.json_requests.append((system, json.loads(content), kwargs))
        reply = next(self.replies)
        if isinstance(reply, BaseException):
            raise reply
        return json.dumps(reply, ensure_ascii=False)


def test_saved_profile_defaults_and_public_schema_have_the_same_closed_values():
    assert Settings().model_dump()["tool_profile"] == "auto"
    assert Settings.model_json_schema()["properties"]["tool_profile"]["enum"] == list(PROFILES)
    schema = Settings.model_json_schema()["properties"]["tool_profile"]
    assert tuple(schema["enum"]) == PROFILES and schema["default"] == "auto"
    with pytest.raises(ValueError):
        Settings(tool_profile="unknown_family")


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("protocol", ["auto", "native", "json"])
def test_selected_profile_and_explicit_protocol_choose_one_existing_port(profile, protocol):
    model = NativeModel([])
    settings = Settings(tool_profile=profile, tool_protocol=protocol)
    before = settings.model_dump()
    selected = agent_native.select_model(host(model), settings)
    portable = protocol == "json" or (protocol == "auto" and profile in PORTABLE_PROFILES)

    assert isinstance(selected, JsonToolPort) is portable
    assert (selected.inner if portable else selected) is model
    assert settings.model_dump() == before
    assert model.requests == model.json_requests == []


@pytest.mark.parametrize("profile", PROFILES)
async def test_profile_retains_the_existing_adapter_fallback_and_explicit_native_error(
    monkeypatch, profile
):
    model = NativeModel([])
    model._apply_provider_options = lambda *_args: None
    check = Mock(side_effect=NativeToolsUnsupportedError("Unsupported local adapter."))
    monkeypatch.setattr(agent_native, "ensure_tools_supported", check)
    selected = agent_native.select_model(host(model), Settings(tool_profile=profile))
    assert isinstance(selected, JsonToolPort)
    assert check.call_count == (profile not in PORTABLE_PROFILES)
    with pytest.raises(RecoverableChpmError, match="Unsupported local adapter"):
        agent_native.select_model(
            host(model), Settings(tool_profile=profile, tool_protocol="native")
        )
    assert model.requests == model.json_requests == []


@pytest.mark.parametrize("profile", ["gemma", "qwen"])
@pytest.mark.parametrize(
    "schema",
    [
        parameters({}),
        parameters({"$ref": "#/$defs/value"}),
        parameters({"anyOf": [{"type": "string"}, {"type": "null"}]}),
        parameters({"type": ["string", "null"]}),
        parameters({"type": "array", "items": {}}),
        parameters({"type": "object", "additionalProperties": {"type": "string"}}),
        parameters({"type": "string", "oneOf": [{"const": "one"}, {"const": "two"}]}),
        parameters({"type": "object", "allOf": [parameters({"type": "string"})]}),
    ],
)
async def test_incompatible_declared_native_shape_is_rejected_before_any_reservation(
    monkeypatch, profile, schema
):
    model, usage = NativeModel([turn()]), Usage()
    settings = Settings(tool_profile=profile, tool_protocol="native")
    dispatched = Mock()
    monkeypatch.setattr(parallel_budget, "dispatched", dispatched)
    before = usage.model_dump(), settings.model_dump(), model.max_tokens

    with pytest.raises(RecoverableChpmError, match="Automatic or JSON"):
        await inference.tool_request(
            host(model), settings, usage, [], definition(schema), llm=model
        )

    assert (usage.model_dump(), settings.model_dump(), model.max_tokens) == before
    assert not dispatched.called and model.requests == model.json_requests == []


@pytest.mark.parametrize("profile", ["gemma", "qwen"])
async def test_actual_notebook_catalog_needs_portable_mode_but_simple_reads_can_be_native(
    profile,
):
    model, usage = NativeModel([turn()]), Usage()
    settings = Settings(tool_profile=profile, tool_protocol="native")
    with pytest.raises(RecoverableChpmError, match="Automatic or JSON"):
        await inference.tool_request(
            host(model), settings, usage, [], tool_definitions(), llm=model
        )
    assert usage.calls == 0 and not model.requests
    simple = tool_definitions(False, available_lookups={"inspect_self", "search_memory"})
    await inference.tool_request(host(model), settings, usage, [], simple, llm=model)
    assert usage.calls == len(model.requests) == 1


@pytest.mark.parametrize("profile", ["gemma", "qwen"])
async def test_schema_checks_do_not_walk_or_rewrite_literal_keys_const_enum_and_defaults(profile):
    literal = {"$ref": "literal", "anyOf": [{"type": "literal"}]}
    schema = parameters(
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "$ref": {"type": "string", "enum": ["literal", "#/$defs/data"]},
                "anyOf": {"type": "array", "items": {"type": "integer"}},
            },
            "const": literal,
            "default": literal,
            "examples": [literal],
        }
    )
    offered = definition(schema)
    before = deepcopy(offered)
    model, usage = NativeModel([turn()]), Usage()
    await inference.tool_request(
        host(model),
        Settings(tool_profile=profile, tool_protocol="native"),
        usage,
        [],
        offered,
        llm=model,
    )
    assert offered == model.requests[0][1] == before and usage.calls == 1


@pytest.mark.parametrize("profile", PROFILES)
async def test_explicit_json_preserves_complete_arbitrary_notebook_values(profile):
    value = {
        "null": None,
        "boolean": False,
        "number": 12.5,
        "text": '  {"$ref":"literal","anyOf":[]}  ',
        "array": [True, None, {"自由": ["null", "12", "true"]}],
    }
    model = PortableReplies(
        [
            {
                "requests": [
                    {
                        "name": "notebook_write",
                        "arguments": {
                            "path": "",
                            "value": value,
                            "expected_revision": 0,
                        },
                    }
                ]
            },
            {"requests": []},
        ]
    )
    draft, usage = NotebookDraft(NotebookWorkspace()), Usage()
    tools, audit = await agent.investigate(
        host(model),
        Settings(
            mode="live",
            actor_ids=["npc"],
            agent_steps=3,
            tool_profile=profile,
            tool_protocol="json",
        ),
        usage,
        mind(),
        observation(),
        {},
        notebook=draft,
    )
    assert json.loads(tools.notebook.workspace.canonical_bytes) == value
    assert tools.notebook.workspace.revision == 1 and tools.notebook.committable
    assert usage.calls == len(model.json_requests) == 2 and not model.requests
    assert audit[-1]["stop"] == "ready" and audit[0]["results"][0]["status"] == "ok"


@pytest.mark.parametrize("profile", PROFILES[1:])
async def test_staged_profile_without_a_notebook_reuses_scoped_lookup_and_early_ready(profile):
    arguments = {"argument": "bridge"}
    model = (
        PortableReplies(
            [
                {"requests": [{"name": "search_memory", "arguments": arguments}]},
                {"requests": []},
            ]
        )
        if profile in PORTABLE_PROFILES
        else NativeModel([turn(call("lookup", "search_memory", arguments)), turn()])
    )
    original = record(mind(), source(text="I promised to inspect the bridge."), minute=1)
    usage = Usage()
    tools, audit = await agent.investigate(
        host(model),
        Settings(mode="live", actor_ids=["npc"], agent_steps=3, tool_profile=profile),
        usage,
        original,
        observation(),
        {},
    )
    assert len(tools.pins) == 1 and tools.notebook is None
    assert next(iter(tools.pins.values()))[2] == "I promised to inspect the bridge."
    assert usage.calls == 2 and audit[-1]["stop"] == "ready"
    assert audit[0]["protocol"] == ("json" if profile in PORTABLE_PROFILES else "native")
    if model.requests:
        names = {entry["function"]["name"] for entry in model.requests[0][1]}
        assert "search_memory" in names and not any(name.startswith("notebook_") for name in names)
        update = json.loads(model.requests[1][0][-1]["content"])["host_context_update"]
        assert update == {"remaining_rounds": 2}


async def test_auto_without_a_notebook_retains_the_legacy_step_port():
    model = Replies(['{"purpose":"Ready","requests":[]}'])
    model.aexecute_tool_turn = Mock(side_effect=AssertionError("Legacy path changed."))
    tools, audit = await agent.investigate(
        host(model),
        Settings(mode="live", actor_ids=["npc"], agent_steps=2),
        Usage(),
        mind(),
        observation(),
        {},
    )
    assert tools.notebook is None and audit[0]["stop"] == "ready"
    assert len(model.requests) == 1 and not model.aexecute_tool_turn.called


async def test_selected_native_profile_never_falls_back_after_an_uncertain_request():
    model, usage = NativeModel([TimeoutError()]), Usage()
    with pytest.raises(InferenceUnavailableError):
        await agent.investigate(
            host(model),
            Settings(mode="live", actor_ids=["npc"], agent_steps=3, tool_profile="openai"),
            usage,
            mind(),
            observation(),
            {},
        )
    assert usage.calls == len(model.requests) == 1 and not model.json_requests
