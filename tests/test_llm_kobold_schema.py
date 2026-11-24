"""The decoder projection preserves exact finite object cardinality."""

from itertools import combinations

import pytest
from jsonschema import Draft202012Validator

from backend.core.llm_kobold_schema import project_cardinality


@pytest.mark.parametrize(("lower", "upper"), [(1, 3), (2, 4)])
def test_closed_candidate_map_preserves_all_valid_combinations(lower, upper):
    properties = {key: {"type": "integer"} for key in "abcdefg"}
    schema = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
        "minProperties": lower,
        "maxProperties": upper,
    }
    projected = project_cardinality(schema)
    assert set(projected) == {"anyOf"}
    checked = Draft202012Validator(projected)
    for size in range(len(properties) + 1):
        for keys in combinations(properties, size):
            assert checked.is_valid(dict.fromkeys(keys, 1)) == (lower <= size <= upper)
    assert not checked.is_valid({"a": 1, "b": "invalid"})
    assert not checked.is_valid({"a": 1, "b": 2, "unknown": 3})
    assert schema["minProperties"] == lower


def test_projection_keeps_existing_required_keys_and_skips_unbounded_maps():
    schema = {
        "type": "object",
        "properties": dict.fromkeys("abc", {"type": "integer"}),
        "required": ["a"],
        "additionalProperties": False,
        "minProperties": 2,
    }
    assert len(project_cardinality(schema)["anyOf"]) == 3
    assert all("a" in branch["required"] for branch in project_cardinality(schema)["anyOf"])
    for unsupported in (
        {**schema, "additionalProperties": True},
        {**schema, "properties": dict.fromkeys("abcdefgh", {"type": "integer"})},
    ):
        assert project_cardinality(unsupported) == unsupported
