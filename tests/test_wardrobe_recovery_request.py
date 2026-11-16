"""Schema feedback retries remain bounded and never bypass evidence validation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.core.inference.registry import InferenceUncertainError
from backend.engine.clothing.recovery_request import request_proposal
from backend.engine.clothing.recovery_schema import RecoveryProposal


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


def test_recovery_schema_enforces_identity_in_json_schema_and_runtime():
    from copy import deepcopy

    from jsonschema import Draft202012Validator

    from tests.test_wardrobe_recovery import entry

    validator = Draft202012Validator(RecoveryProposal.model_json_schema())
    valid_new = entry("source").model_dump()
    valid_existing = deepcopy(valid_new)
    valid_existing["action"].update(item_id="COAT", new_item=None)
    both = deepcopy(valid_new)
    both["action"]["item_id"] = "invented_id"
    neither = deepcopy(valid_existing)
    neither["action"]["item_id"] = None
    for candidate in [valid_new, valid_existing]:
        wire = {"entries": [candidate]}
        assert not list(validator.iter_errors(wire))
        RecoveryProposal.model_validate(wire)
    for candidate in [both, neither]:
        wire = {"entries": [candidate]}
        assert list(validator.iter_errors(wire))
        with pytest.raises(ValidationError):
            RecoveryProposal.model_validate(wire)
    assert not list(validator.iter_errors({"entries": [valid_new] * 16}))
    assert list(validator.iter_errors({"entries": [valid_new] * 17}))


@pytest.mark.asyncio
async def test_eight_conflicting_identities_retry_with_concrete_field_errors():
    from tests.test_wardrobe_recovery import entry

    valid = {"entries": [entry("source", name=f"Coat {index}").model_dump() for index in range(8)]}
    invalid = {"entries": [entry("source").model_dump() for _ in range(8)]}
    for row in invalid["entries"]:
        row["action"]["item_id"] = "invented_id"
    llm = SimpleNamespace(
        model="test", aexecute_complex_task=AsyncMock(side_effect=[invalid, valid])
    )
    result = await request_proposal(llm, "Instructions", "History", RecoveryProposal, "session")
    assert len(result.entries) == 8
    feedback = llm.aexecute_complex_task.call_args_list[1].args[0]
    assert "new_item: none_required" in feedback and "item_id: none_required" in feedback
    assert "invented_id" not in feedback


def test_validator_hints_are_allowlisted_and_never_echo_model_values():
    from backend.engine.clothing.recovery_request import schema_issues
    from backend.engine.narrated_items.schema import ItemAction

    with pytest.raises(ValidationError) as failure:
        ItemAction.model_validate(
            {
                "item_id": None,
                "new_item": None,
                "source_owner": "private",
                "destination_owner": "private",
                "disposition": "worn",
                "basis": "observed_wear",
                "evidence": "private narration",
            }
        )
    issues = schema_issues(failure.value)
    assert "supply exactly one of item_id and new_item" in issues
    assert "private" not in issues
