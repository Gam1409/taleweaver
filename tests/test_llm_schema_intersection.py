"""Finite intersections preserve JSON equality and scalar numeric type semantics."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from backend.core.llm_schema_merge import intersect


@pytest.mark.parametrize(
    "left,right",
    [
        ({"type": "integer"}, {"const": 1.0}),
        ({"type": "number"}, {"const": 1}),
        ({"const": 1}, {"const": 1.0}),
        ({"enum": [False, 0, 1]}, {"const": 1.0}),
        ({"enum": [False, 0]}, {"const": 0.0}),
        ({"enum": [1.0, 2.0]}, {"type": "integer"}),
        ({"enum": [True, 1]}, {"type": "number"}),
        ({"type": "integer"}, {"const": 1.5}),
        ({"enum": [[False], [0]]}, {"const": [0]}),
        ({"const": {"flag": False}}, {"const": {"flag": 0}}),
        ({"const": {"values": [1]}}, {"const": {"values": [1.0]}}),
        ({"const": {"a": 1, "b": False}}, {"const": {"b": False, "a": 1.0}}),
        ({"type": "integer", "minimum": 1, "maximum": 3}, {"enum": [1.0, 2.0, 4.0]}),
    ],
)
def test_finite_intersections_match_the_original_json_contract(left, right):
    original = deepcopy((left, right))
    host = Draft202012Validator({"allOf": [left, right]})
    decoder = Draft202012Validator(intersect(left, right))
    for value in (
        None,
        False,
        True,
        0,
        0.0,
        1,
        1.0,
        1.5,
        2,
        2.0,
        4.0,
        "1",
        [],
        [False],
        [0],
        {"flag": False},
        {"flag": 0},
        {"values": [1]},
        {"values": [1.0]},
        {"a": 1, "b": False},
        {"b": False, "a": 1.0},
    ):
        assert decoder.is_valid(value) is host.is_valid(value), value
    assert (left, right) == original
