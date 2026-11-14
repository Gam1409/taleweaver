"""Tool completion metadata stays safe without changing ordinary completion semantics."""

import json
from dataclasses import asdict

import pytest

from backend.core.llm_completion_capture import Completion, capture_completions, record_completion
from backend.core.llm_finish_state import classify_tool_finish


@pytest.mark.parametrize("reason", [None, "stop", "tool_calls", "length", "max_tokens"])
def test_complete_or_truncated_canonical_tool_flags_remain_distinguishable(reason):
    assert classify_tool_finish({"finish_reason": reason}) == reason


def test_absent_reason_is_compatible_and_primary_truncation_cannot_be_downgraded():
    assert classify_tool_finish({}) is None
    assert (
        classify_tool_finish(
            {
                "finish_reason": "length",
                "provider_specific_fields": {"native_finish_reason": "end_turn"},
            }
        )
        == "length"
    )


@pytest.mark.parametrize("native", ["max_tokens", "MAX_TOKENS", "compaction"])
def test_preserved_native_truncation_overrides_normalized_stop(native):
    assert (
        classify_tool_finish(
            {
                "finish_reason": "stop",
                "provider_specific_fields": {"native_finish_reason": native},
            }
        )
        == "length"
    )


@pytest.mark.parametrize(
    "reason", ["content_filter", "function_call", "PRIVATE_FINISH_CANARY", {}, []]
)
def test_untrusted_flags_raise_static_feedback_without_copying_the_flag(reason):
    with pytest.raises(ValueError) as error:
        classify_tool_finish({"finish_reason": reason})
    assert str(error.value) == "The tool response has an unsupported finish reason."


@pytest.mark.parametrize("choice", [None, [], True, "PRIVATE_CHOICE_CANARY"])
def test_ambiguous_choice_shapes_cannot_certify_a_tool_response(choice):
    with pytest.raises(ValueError):
        classify_tool_finish(choice)


def test_completion_constructor_remains_compatible_with_two_positional_arguments():
    value = Completion("stop", 12)
    assert value.finish_reason == "stop" and value.completion_tokens == 12
    assert value.tool_finish_reason is None and value.tool_rejected is False


@pytest.mark.parametrize(
    ("reason", "expected_legacy", "rejected"),
    [("stop", "stop", False), ("content_filter", "content_filter", True), ("unknown", None, True)],
)
def test_recording_retains_legacy_fields_and_adds_separate_safe_tool_state(
    reason, expected_legacy, rejected
):
    with capture_completions() as records:
        record_completion(
            {"choices": [{"finish_reason": reason}], "usage": {"completion_tokens": 8}}
        )

    value = records[0]
    assert value.finish_reason == expected_legacy and value.completion_tokens == 8
    assert value.tool_rejected is rejected
    assert value.tool_finish_reason == (None if rejected else reason)


def test_normalized_unknown_flags_keep_only_rejection_and_usage_not_private_metadata():
    canary = "PRIVATE_FINISH_AND_CONTENT_CANARY"
    response = {
        "choices": [
            {
                "finish_reason": "stop",
                "provider_specific_fields": {"native_finish_reason": canary},
                "message": {"content": canary},
            }
        ],
        "usage": {"completion_tokens": 8},
    }
    with capture_completions() as records:
        record_completion(response)

    assert asdict(records[0]) == {
        "finish_reason": "stop",
        "completion_tokens": 8,
        "tool_finish_reason": None,
        "tool_rejected": True,
    }
    assert canary not in json.dumps(asdict(records[0]))


def test_recording_native_truncation_does_not_reinterpret_ordinary_finish_reason():
    with capture_completions() as records:
        record_completion(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "provider_specific_fields": {"native_finish_reason": "MAX_TOKENS"},
                    }
                ],
                "usage": {"completion_tokens": 8},
            }
        )

    assert records[0].finish_reason == "stop"
    assert records[0].tool_finish_reason == "length" and not records[0].tool_rejected


def test_ambiguous_completion_choices_reject_tools_but_preserve_legacy_unknown_state():
    with capture_completions() as records:
        record_completion({"choices": [{}, {}], "usage": {"completion_tokens": 8}})

    assert records[0].finish_reason is None and records[0].completion_tokens is None
    assert records[0].tool_finish_reason is None and records[0].tool_rejected
