"""Wrong note-derived handles receive bounded guidance without granting authority."""

import json
from copy import deepcopy

import pytest

from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.notebook import NotebookWorkspace
from backend.engine.chpm.notebook_tools import NotebookDraft
from tests.test_chpm_native_notebook_loop import call, investigate, turn

PRIVATE = "OPAQUE_PRIVATE_NOTE_HANDLE_4E1"


class CorrectingModel:
    model = "offline-correcting"
    max_tokens = 1200
    request_timeout = 1

    def __init__(self, protocol, wrong_tool, handle_field, producer):
        self.protocol, self.wrong_tool = protocol, wrong_tool
        self.handle_field, self.producer = handle_field, producer
        self.feedback, self.requests = [], []

    def respond(self, results):
        index = len(self.requests)
        self.feedback = results
        if index == 1:
            return "notebook_read", {"path": ""}
        if index == 2:
            assert PRIVATE in results[-1]["json_fragment"]
            return self.wrong_tool, {"argument": PRIVATE}
        message = results[-1].get("message", "")
        if (
            self.handle_field in message
            and self.producer in message
            and "notebook" in message.casefold()
        ):
            return "notebook_read", {"path": "/private"}
        return None, None

    async def aexecute_tool_turn(self, messages, tools, model, **kwargs):
        assert self.protocol == "native"
        self.requests.append(deepcopy(messages))
        results = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        name, arguments = self.respond(results)
        return turn(call(f"round-{len(self.requests)}", name, arguments)) if name else turn()

    async def aexecute_simple_task(self, system, content, model, **kwargs):
        assert self.protocol == "json"
        payload = json.loads(content)
        self.requests.append(payload)
        results = [item for batch in payload["previous_lookups"] for item in batch["results"]]
        name, arguments = self.respond(results)
        return json.dumps({"requests": [{"name": name, "arguments": arguments}] if name else []})


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize(
    ("wrong_tool", "status", "handle_field", "producer"),
    [
        ("read_belief_basis", "unavailable_belief", "belief_id", "inspect_beliefs"),
        ("read_memory", "unavailable_source", "memory_id", "search_memory"),
    ],
)
async def test_note_text_mistaken_for_a_handle_receives_guidance_then_correct_notebook_read(
    protocol, wrong_tool, status, handle_field, producer
):
    draft = NotebookDraft(NotebookWorkspace(json.dumps({"private": PRIVATE}).encode()))
    original = draft.workspace.canonical_bytes
    model = CorrectingModel(protocol, wrong_tool, handle_field, producer)

    tools, audit, usage = await investigate(model, draft=draft, steps=3, protocol=protocol)

    assert len(model.requests) == usage.calls == 3
    assert [step["results"][0]["status"] for step in audit] == ["ok", status, "ok"]
    assert tools.notebook.reads[-1]["json_fragment"] == json.dumps(PRIVATE)
    assert tools.notebook.workspace.canonical_bytes == original and not draft.workspace.changed
    assert draft.workspace.revision == draft.workspace.base_revision == 0
    assert not tools.beliefs and not tools.pins and not tools.exposed
    assert tools.execute(Lookup(tool=wrong_tool, argument=PRIVATE)) == {"status": status}
    hint = model.feedback[-1]
    assert hint["status"] == status and PRIVATE not in hint["message"]
    assert len(hint["message"]) <= 200
    assert handle_field in hint["message"] and producer in hint["message"]
    assert audit[1]["results"] == [{"status": status}]
    assert PRIVATE not in json.dumps(audit) and "message" not in audit[1]["results"][0]


def test_corrective_feedback_is_narrow_static_and_preserves_existing_precise_messages():
    from backend.engine.chpm.tool_feedback import for_model

    original = {"status": "unavailable_belief", "message": "A precise existing explanation."}
    result = for_model("read_belief_basis", original)
    assert original == {
        "status": "unavailable_belief",
        "message": "A precise existing explanation.",
    }
    assert result["message"] == original["message"]
    assert "belief_id" in result["corrective_hint"] and len(result["corrective_hint"]) <= 200
    for tool, status in [
        ("notebook_read", "unavailable_belief"),
        ("read_memory", "ok"),
        ("unknown_tool", "unavailable_source"),
    ]:
        unchanged = {"status": status}
        assert for_model(tool, unchanged) is unchanged
