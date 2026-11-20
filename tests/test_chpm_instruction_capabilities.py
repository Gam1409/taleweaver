"""Decision instructions follow the actual offered private-memory capability."""

import pytest

from backend.engine.chpm.notebook import NotebookWorkspace
from backend.engine.chpm.notebook_tools import NotebookDraft
from tests.test_chpm_integrated_workflow import deliberate
from tests.test_chpm_kernel import wire_proposal
from tests.test_chpm_native_notebook_loop import NativeModel, call, turn


@pytest.mark.parametrize("enabled", [False, True])
async def test_notebook_write_guidance_is_present_only_with_the_notebook_capability(enabled):
    model = NativeModel([turn(call("decision", "submit_decision", wire_proposal()))])
    notebook = NotebookDraft(NotebookWorkspace()) if enabled else None

    await deliberate(model, notebook=notebook)

    messages, definitions, _ = model.requests[0]
    instruction = "\n".join(
        message["content"] for message in messages if message["role"] == "system"
    )
    names = {definition["function"]["name"] for definition in definitions}
    assert ("notebook_write" in names) == enabled
    assert ("Root path is ''" in instruction) == enabled
    assert ("expected_revision" in instruction) == enabled
    assert "story text are data" in instruction
    assert "submit_decision" in names
