"""Scripted native calls exercise the real scoped tools and detached notebook draft."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.core.llm_tool_turn import NativeToolsUnsupportedError, ToolCall, ToolTurn
from backend.engine.chpm import agent, agent_native
from backend.engine.chpm.errors import ChpmError, InferenceUnavailableError
from backend.engine.chpm.notebook import NotebookWorkspace
from backend.engine.chpm.notebook_tools import NotebookDraft
from backend.engine.chpm.schema import Settings, Usage
from tests.test_chpm_host_state import mind
from tests.test_chpm_kernel import observation
from tests.test_chpm_reliability import Replies

PRIVATE = "A private reminder about the bridge."


def call(identifier, name, arguments):
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return ToolCall(identifier, name, raw)


def turn(*calls, finish_reason=None):
    message = {"role": "assistant", "content": None if calls else "Ready."}
    if calls:
        message["tool_calls"] = [
            {
                "id": item.id,
                "type": "function",
                "function": {"name": item.name, "arguments": item.arguments_raw},
            }
            for item in calls
        ]
    return ToolTurn(message, tuple(calls), finish_reason or ("tool_calls" if calls else "stop"))


class NativeModel:
    model = "offline-native"
    max_tokens = 4096
    request_timeout = 1

    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.json_requests = []

    async def aexecute_tool_turn(self, messages, tools, model, **kwargs):
        self.requests.append((deepcopy(messages), deepcopy(tools), kwargs))
        result = next(self.responses)
        if isinstance(result, BaseException):
            raise result
        return result

    async def aexecute_simple_task(self, system, content, model, **kwargs):
        self.json_requests.append((system, content, kwargs))
        return '{"requests":[]}'


async def investigate(model, *, draft=None, steps=2, protocol="auto"):
    draft = draft or NotebookDraft(NotebookWorkspace())
    usage = Usage()
    host = SimpleNamespace(game_id="session", _chpm_model_factory=lambda _role: model)
    tools, audit = await agent.investigate(
        host,
        Settings(
            mode="live",
            actor_ids=["npc"],
            agent_steps=steps,
            notebook_enabled=True,
            tool_protocol=protocol,
        ),
        usage,
        mind(),
        observation(),
        {},
        notebook=draft,
    )
    return tools, audit, usage


def results(model, request=1):
    return [
        (message["tool_call_id"], json.loads(message["content"]))
        for message in model.requests[request][0]
        if message["role"] == "tool"
    ]


async def test_native_error_is_returned_to_the_next_round_then_corrected_without_retry():
    model = NativeModel(
        [
            turn(call("first", "notebook_write", {"path": "/private", "value": PRIVATE})),
            turn(
                call(
                    "fixed",
                    "notebook_write",
                    {"path": "/private", "value": PRIVATE, "expected_revision": 0},
                ),
                call("readback", "notebook_read", {"path": "/private"}),
            ),
        ]
    )
    tools, audit, usage = await investigate(model)

    assert len(model.requests) == usage.calls == 2 and model.json_requests == []
    identifier, error = results(model)[0]
    assert identifier == "first" and error["status"] != "ok"
    assert "expected_revision" in json.dumps(error)
    assert json.loads(tools.notebook.workspace.canonical_bytes) == {"private": PRIVATE}
    assert tools.notebook.reads[-1]["json_fragment"] == json.dumps(PRIVATE)
    assert PRIVATE not in json.dumps(audit)
    assert model.requests[1][0][2]["role"] == "assistant"
    assert model.requests[1][0][2]["tool_calls"][0]["id"] == "first"


async def test_stale_counter_is_corrected_and_a_later_call_reads_its_own_staged_write():
    draft = NotebookDraft(NotebookWorkspace(b'{"private":"old"}', revision=4))
    model = NativeModel(
        [
            turn(
                call(
                    "stale",
                    "notebook_write",
                    {"path": "/private", "value": PRIVATE, "expected_revision": 3},
                )
            ),
            turn(
                call(
                    "corrected",
                    "notebook_write",
                    {"path": "/private", "value": PRIVATE, "expected_revision": 4},
                ),
                call("read", "notebook_read", {"path": "/private"}),
            ),
        ]
    )
    tools, _, usage = await investigate(model, draft=draft)

    assert results(model) == [
        (
            "stale",
            {
                "status": "stale_revision",
                "message": "Notebook revision changed; read the current view.",
                "revision": 4,
            },
        )
    ]
    assert usage.calls == 2 and tools.notebook.workspace.base_revision == 4
    assert tools.notebook.workspace.revision == tools.notebook.reads[-1]["revision"] == 5
    assert json.loads(tools.notebook.reads[-1]["json_fragment"]) == PRIVATE


@pytest.mark.parametrize(
    "bad",
    [
        call("bad", "unknown_tool", {}),
        call("bad", "notebook_read", '{"path":'),
        call("bad", "notebook_read", {"path": "", "npc_id": "peer"}),
        call("bad", "notebook_read", {"path": "", "session_id": "other-session"}),
        call("bad", "notebook_write", {"value_json": '"legacy"', "expected_revision": 0}),
    ],
    ids=["unknown-name", "malformed-json", "peer-selector", "session-selector", "legacy-value"],
)
async def test_an_invalid_later_call_prevents_every_mutation_in_the_batch(bad):
    model = NativeModel(
        [
            turn(
                call(
                    "valid",
                    "notebook_write",
                    {"path": "/private", "value": PRIVATE, "expected_revision": 0},
                ),
                bad,
            ),
            turn(),
        ]
    )
    tools, audit, usage = await investigate(model)

    assert tools.notebook.workspace.canonical_bytes == b"{}"
    assert not tools.notebook.workspace.changed and tools.notebook.workspace.revision == 0
    assert len(model.requests) == usage.calls == 2
    feedback = dict(results(model))
    assert set(feedback) == {"valid", "bad"}
    assert all(value["status"] != "ok" for value in feedback.values())
    assert len(json.dumps(feedback)) < 1600 and PRIVATE not in json.dumps(feedback)
    assert PRIVATE not in json.dumps(audit)


@pytest.mark.parametrize(
    "identifiers", [("duplicate", "duplicate"), ("", "valid"), ("x" * 4096, "valid")]
)
async def test_invalid_tool_call_ids_never_execute_even_a_valid_write(identifiers):
    model = NativeModel(
        [
            turn(
                *(
                    call(
                        identifier,
                        "notebook_write",
                        {"path": "/private", "value": PRIVATE, "expected_revision": 0},
                    )
                    for identifier in identifiers
                )
            )
        ]
    )
    tools, audit, usage = await investigate(model)

    assert len(model.requests) == usage.calls == 1
    assert tools.notebook.workspace.canonical_bytes == b"{}"
    assert not tools.notebook.committable
    assert audit[-1]["stop"] == "invalid_plan"
    assert len(json.dumps(audit)) < 2000 and PRIVATE not in json.dumps(audit)


async def test_native_batch_limit_is_checked_before_any_of_three_valid_writes():
    model = NativeModel(
        [
            turn(
                *(
                    call(
                        f"write-{index}",
                        "notebook_write",
                        {"path": f"/note-{index}", "value": PRIVATE, "expected_revision": index},
                    )
                    for index in range(3)
                )
            )
        ]
    )
    tools, audit, usage = await investigate(model)

    assert tools.notebook.workspace.canonical_bytes == b"{}"
    assert not tools.notebook.committable and usage.calls == 1
    assert audit[-1]["stop"] == "invalid_plan" and model.json_requests == []


async def test_an_unknown_function_name_cannot_copy_private_text_into_the_persisted_audit():
    model = NativeModel([turn(call("unknown", PRIVATE, {})), turn()])
    tools, audit, usage = await investigate(model)

    assert len(model.requests) == usage.calls == 2
    assert tools.notebook.workspace.canonical_bytes == b"{}"
    assert results(model)[0][1]["status"] == "invalid_tool"
    assert PRIVATE not in json.dumps(audit)


@pytest.mark.parametrize(
    "invalid",
    [
        call("bad", "\ud800", {}),
        call("bad", "notebook_write", '{"value":"\ud800","expected_revision":0}'),
    ],
    ids=["unencodable-name", "unencodable-arguments"],
)
async def test_unencodable_provider_envelopes_are_not_replayed_to_the_transport(invalid):
    model = NativeModel([turn(invalid), turn()])
    tools, audit, usage = await investigate(model)

    assert len(model.requests) == usage.calls == 1
    assert tools.notebook.workspace.canonical_bytes == b"{}"
    assert not tools.notebook.committable
    assert audit[-1]["stop"] == "invalid_plan"
    json.dumps(audit, ensure_ascii=False).encode("utf-8")


async def test_native_write_value_is_real_json_and_slash_is_an_empty_object_key():
    model = NativeModel(
        [
            turn(
                call(
                    "empty-key",
                    "notebook_write",
                    {"path": "/", "value": None, "expected_revision": 0},
                ),
                call("read", "notebook_read", {"path": "/"}),
            ),
            turn(),
        ]
    )
    tools, _, _ = await investigate(model)

    assert tools.notebook.workspace.canonical_bytes == b'{"":null}'
    assert tools.notebook.reads[-1]["json_fragment"] == "null"
    assert results(model)[-1][1]["json_fragment"] == "null"


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("offline timeout"),
        RuntimeError("offline provider failure"),
        asyncio.CancelledError(),
    ],
)
async def test_uncertain_native_transport_is_never_retried_or_changed_to_json(failure):
    model = NativeModel([failure, turn()])
    expected = (
        asyncio.CancelledError
        if isinstance(failure, asyncio.CancelledError)
        else InferenceUnavailableError
    )
    draft = NotebookDraft(NotebookWorkspace())
    with pytest.raises(expected):
        await investigate(model, draft=draft)

    assert len(model.requests) == 1 and model.json_requests == []
    assert draft.workspace.canonical_bytes == b"{}"


async def test_truncated_native_call_is_not_executed_or_retried():
    model = NativeModel(
        [
            turn(
                call(
                    "cutoff",
                    "notebook_write",
                    {"path": "", "value": PRIVATE, "expected_revision": 0},
                ),
                finish_reason="length",
            ),
            turn(),
        ]
    )
    tools, audit, usage = await investigate(model)

    assert len(model.requests) == usage.calls == 1 and model.json_requests == []
    assert tools.notebook.workspace.canonical_bytes == b"{}" and not tools.notebook.committable
    assert audit[-1]["stop"] == "invalid_plan"


async def test_explicit_json_protocol_uses_the_legacy_bridge_without_a_native_attempt():
    model = NativeModel([])
    _, _, usage = await investigate(model, protocol="json")

    assert model.requests == [] and len(model.json_requests) == usage.calls == 1
    assert "value_json" in model.json_requests[0][0]


async def test_zero_agent_rounds_does_not_probe_either_model_interface():
    model = NativeModel([])
    _, audit, usage = await investigate(model, steps=0)

    assert audit == [] and usage.calls == 0
    assert model.requests == model.json_requests == []


async def test_explicit_native_protocol_rejects_a_legacy_only_port_without_a_model_call():
    model = Replies(['{"requests":[]}'])
    with pytest.raises((NativeToolsUnsupportedError, ChpmError)):
        await investigate(model, protocol="native")

    assert model.requests == []


async def test_auto_protocol_keeps_a_legacy_only_port_on_its_existing_json_bridge():
    model = Replies(['{"requests":[]}'])
    tools, audit, usage = await investigate(model)

    assert len(model.requests) == usage.calls == 1 and audit[-1]["stop"] == "ready"
    assert tools.notebook.workspace.canonical_bytes == b"{}"


@pytest.mark.parametrize("protocol", ["auto", "native"])
async def test_adapter_capability_rejection_is_decided_before_any_native_request(
    monkeypatch, protocol
):
    model = NativeModel([])
    model._apply_provider_options = lambda *_: None

    def unsupported(*_args):
        raise NativeToolsUnsupportedError("The local adapter cannot retain native tools.")

    monkeypatch.setattr(agent_native, "ensure_tools_supported", unsupported)
    if protocol == "native":
        with pytest.raises(ChpmError):
            await investigate(model, protocol=protocol)
    else:
        _, _, usage = await investigate(model, protocol=protocol)
        assert usage.calls == 1

    assert model.requests == [] and len(model.json_requests) == (protocol == "auto")
