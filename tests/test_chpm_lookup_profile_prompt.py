"""Captured lookup turns advertise available reads and retain existing prompt controls."""

import hashlib
import json

import pytest

from backend.engine.chpm import agent, agent_contracts, agent_native
from backend.engine.chpm.host_state import record
from backend.engine.chpm.notebook import NotebookWorkspace
from backend.engine.chpm.notebook_tools import NotebookDraft
from backend.engine.chpm.schema import Settings, Usage
from tests.test_chpm_agent_tools import current
from tests.test_chpm_host_state import mind, source
from tests.test_chpm_kernel import observation
from tests.test_chpm_native_notebook_loop import NativeModel, call, turn
from tests.test_chpm_reliability import Replies
from tests.test_chpm_tool_profiles import PortableReplies, host

NOTEBOOK_PROMPT_SHA256 = "85f66b3f47e7b06efeb1f012a751c9d23d6ae1d2c2602b8ea8d5ed1f29e5d58e"
MEMORY = "I promised to inspect the bridge."


def reader(profile):
    requests = [
        {"name": "inspect_self", "arguments": {}},
        {"name": "search_memory", "arguments": {"argument": "bridge"}},
    ]
    if profile in {"gemma", "qwen"}:
        return PortableReplies([{"requests": requests}, {"requests": []}])
    return NativeModel(
        [
            turn(
                *(
                    call(f"read-{index}", request["name"], request["arguments"])
                    for index, request in enumerate(requests)
                )
            ),
            turn(),
        ]
    )


async def investigate(model, profile, *, notebook=None):
    original = current(record(mind(), source("old", MEMORY), minute=1))
    settings = Settings(mode="live", actor_ids=["npc"], agent_steps=3, tool_profile=profile)
    before = settings.model_dump()
    usage = Usage()
    tools, audit = await agent.investigate(
        host(model),
        settings,
        usage,
        original,
        observation(),
        {},
        notebook=notebook,
    )
    assert settings.model_dump() == before
    assert tools.mind == original
    assert {entry[1].message_id for entry in tools.pins.values()} == {"old", "input"}
    assert MEMORY in {entry[2] for entry in tools.pins.values()}
    assert [result["status"] for result in audit[0]["results"]] == ["ok", "ok"]
    assert audit[-1]["stop"] == "ready" and usage.calls == 2
    return tools, audit


@pytest.mark.parametrize("profile", ["anthropic", "openai", "mistral", "deepseek", "gemma", "qwen"])
async def test_lookup_only_profile_runs_two_scoped_reads_then_ready_without_write_instructions(
    profile,
):
    model = reader(profile)
    tools, audit = await investigate(model, profile)
    assert tools.notebook is None
    if model.requests:
        prompt = model.requests[0][0][0]["content"]
        names = {entry["function"]["name"] for entry in model.requests[0][1]}
        assert names.issuperset({"inspect_self", "search_memory"})
        assert not any(name.startswith("notebook_") for name in names)
        assert len(model.requests) == 2 and not model.json_requests
        assert audit[0]["protocol"] == "native"
    else:
        prompt, payload, _options = model.json_requests[0]
        assert "personal_notebook" not in payload
        assert len(model.json_requests) == 2 and audit[0]["protocol"] == "json"
        assert '"name":"function_name","arguments":{}' in prompt
        assert "At most two requests; [] when ready." in prompt

    assert "Choose only necessary read-only lookups" in prompt
    assert "Use only offered functions; stop without calls when" in prompt
    assert "inspect_self():" in prompt and "inspect_scene():" in prompt
    assert "inspect_self(argument='')" not in prompt
    assert "inspect_scene(argument='')" not in prompt
    assert "Return requests=[]" not in prompt and "Return a short purpose" not in prompt
    assert "Organize JSON notes" not in prompt and "Write JSON values" not in prompt
    assert "expected_revision" not in prompt
    assert "Historical reports are not world facts; newer host state wins." in prompt
    assert "Do not propose actions or edit psychological state yet." in prompt


@pytest.mark.parametrize("profile", ["auto", "gemma"])
async def test_available_notebook_keeps_the_exact_existing_native_instruction_bytes(profile):
    model = reader(profile)
    draft = NotebookDraft(NotebookWorkspace())
    await investigate(model, profile, notebook=draft)
    assert hashlib.sha256(agent_native.INSTRUCTIONS.encode()).hexdigest() == NOTEBOOK_PROMPT_SHA256
    if model.requests:
        assert model.requests[0][0][0]["content"] == agent_native.INSTRUCTIONS
    else:
        prompt, payload, _options = model.json_requests[0]
        assert prompt.endswith(agent_native.INSTRUCTIONS)
        assert payload["personal_notebook"]["revision"] == 0
    assert draft.workspace.canonical_bytes == b"{}" and draft.workspace.revision == 0


async def test_auto_without_notebook_keeps_its_legacy_step_instructions_and_execution():
    model = Replies(
        [
            json.dumps(
                {
                    "requests": [
                        {"tool": "inspect_self"},
                        {"tool": "search_memory", "argument": "bridge"},
                    ]
                }
            ),
            '{"purpose":"Ready","requests":[]}',
        ]
    )
    _tools, audit = await investigate(model, "auto")
    prompt = model.requests[0][1]
    assert prompt.startswith(agent_contracts.INSTRUCTIONS)
    assert "Return requests=[] when the available information is sufficient." in prompt
    assert "protocol" not in audit[0] and len(model.requests) == 2
