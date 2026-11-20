"""Action correction names real fields and constraints without leaking supplied values."""

import json

import pytest

from backend.engine.chpm.native_tool_contracts import NativeToolArgumentError, parse_call


@pytest.mark.parametrize(
    "name,arguments,expected",
    [
        ("take_item", {}, ("item_id", "string")),
        ("give_item", {"item_id": "KEY", "recipient_id": 42}, ("recipient_id", "string")),
        ("use_item", {"item_id": "KEY", "extent": "some"}, ("extent", "partial", "full")),
        (
            "adjust_clothing",
            {"item_id": "COAT", "uncovered_regions": ["middle"]},
            ("uncovered_regions[0]", "torso", "arms"),
        ),
        (
            "change_item_state",
            {"item_id": "KEY", "dimension": "Bad Dimension", "detail": "A detail."},
            ("dimension", "[a-z]"),
        ),
    ],
)
def test_action_argument_feedback_reports_the_relevant_schema_constraint(name, arguments, expected):
    with pytest.raises(NativeToolArgumentError) as failure:
        parse_call(name, json.dumps(arguments))
    message = failure.value.message
    assert all(part in message for part in expected)
    assert "op, path and value" not in message
    assert len(message) <= 400


def test_unknown_argument_names_and_private_values_do_not_appear_in_feedback():
    name = "PRIVATE_ARGUMENT_NAME_CANARY"
    value = "PRIVATE_ARGUMENT_VALUE_CANARY"
    with pytest.raises(NativeToolArgumentError) as failure:
        parse_call("take_item", json.dumps({name: value}))
    assert name not in failure.value.message and value not in failure.value.message
    assert "item_id" in failure.value.message


def test_action_feedback_retains_multiple_distinct_known_fields():
    with pytest.raises(NativeToolArgumentError) as failure:
        parse_call("give_item", '{"item_id":false,"recipient_id":null}')
    assert "item_id" in failure.value.message and "recipient_id" in failure.value.message
    assert len(failure.value.message) <= 400
