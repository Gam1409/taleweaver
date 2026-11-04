"""Schema feedback retries remain bounded and never bypass evidence validation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.core.inference.registry import InferenceUncertainError
from backend.engine.clothing.recovery import RecoveryProposal
from backend.engine.clothing.recovery_request import request_proposal


def invalid_response():
    try:
        RecoveryProposal.model_validate({"entries": [{"source_message_id": "source"}]})
    except ValidationError as exc:
        wrapped = ValueError("Validation errors: 1.")
        wrapped.__cause__ = exc
        return wrapped
    raise AssertionError("Expected validation failure")


@pytest.mark.asyncio
async def test_retries_schema_failure_with_field_feedback():
    valid = RecoveryProposal(notes="No evidence.")
    llm = SimpleNamespace(
        model="test", aexecute_complex_task=AsyncMock(side_effect=[invalid_response(), valid])
    )
    result = await request_proposal(llm, "Instructions", "History", RecoveryProposal, "session")
    assert result == valid
    first, second = llm.aexecute_complex_task.call_args_list
    assert first.kwargs["phase"] == "preview"
    assert second.kwargs["phase"] == "schema_retry"
    assert "entries.0.action: missing" in second.args[0]
    assert second.args[1] == first.args[1] == "History"


@pytest.mark.asyncio
async def test_second_schema_failure_is_visible_and_not_retried_again():
    llm = SimpleNamespace(
        model="test", aexecute_complex_task=AsyncMock(side_effect=invalid_response())
    )
    with pytest.raises(ValueError, match=r"after one retry: entries.0.action: missing"):
        await request_proposal(llm, "Instructions", "History", RecoveryProposal, "session")
    assert llm.aexecute_complex_task.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [InferenceUncertainError("Blocked"), TimeoutError(), ValueError("Not JSON")]
)
async def test_transport_and_non_schema_failures_do_not_retry(failure):
    llm = SimpleNamespace(model="test", aexecute_complex_task=AsyncMock(side_effect=failure))
    with pytest.raises(type(failure)):
        await request_proposal(llm, "Instructions", "History", RecoveryProposal, "session")
    assert llm.aexecute_complex_task.await_count == 1
