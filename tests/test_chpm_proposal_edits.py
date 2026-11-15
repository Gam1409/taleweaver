"""Repair paths address JSON data only and never bypass the original contract."""

from copy import deepcopy

import pytest
from pydantic import BaseModel

from backend.engine.chpm import proposal_edits


class Proposal(BaseModel):
    value: str


def edits(*items):
    return proposal_edits.Corrections.model_validate({"edits": list(items)})


def test_replacements_preserve_exact_unedited_values_and_original_object():
    original = {"value": "bad", "nested": {"quote": '"Не меняй…"'}, "rows": ["one", "two"]}
    before = deepcopy(original)
    result = proposal_edits.apply(
        original,
        edits(
            {"op": "replace", "path": "/value", "value": "correct"},
            {"op": "replace", "path": "/rows/1", "value": "updated"},
        ),
        Proposal,
    )
    assert result == {"value": "correct", "nested": before["nested"], "rows": ["one", "updated"]}
    assert original == before


def test_pointer_escaping_and_command_like_values_are_plain_json_data():
    original = {"value": "old", "a/b~c": "unchanged"}
    text = "$(touch /not-a-real-command); __import__('os').system('ignored')"
    changed = proposal_edits.apply(
        original, edits({"op": "replace", "path": "/a~1b~0c", "value": text}), Proposal
    )
    assert changed["a/b~c"] == text
    assert original["a/b~c"] == "unchanged"


@pytest.mark.parametrize("value", [{}, {"value": None}])
def test_remove_accepts_omitted_or_strict_decoder_null_value(value):
    original = {"value": "retained", "extra": "remove me"}
    changed = proposal_edits.apply(
        original, edits({"op": "remove", "path": "/extra", **value}), Proposal
    )
    assert changed == {"value": "retained"}
    assert original["extra"] == "remove me"


@pytest.mark.parametrize(
    "items",
    [
        [{"op": "replace", "path": "/settings", "value": "invented"}],
        [{"op": "replace", "path": "/rows/9", "value": "invented"}],
        [{"op": "replace", "path": "/rows/-1", "value": "invented"}],
        [{"op": "replace", "path": "/rows/00", "value": "invented"}],
        [{"op": "remove", "path": "/rows/0"}],
        [
            {"op": "replace", "path": "/value", "value": "one"},
            {"op": "replace", "path": "/value", "value": "two"},
        ],
        [
            {"op": "replace", "path": "/rows", "value": []},
            {"op": "replace", "path": "/rows/0", "value": "one"},
        ],
    ],
)
def test_unavailable_ambiguous_or_index_shifting_edits_reject_without_mutation(items):
    original = {"value": "unchanged", "rows": ["one", "two"]}
    before = deepcopy(original)
    with pytest.raises(ValueError):
        proposal_edits.apply(original, edits(*items), Proposal)
    assert original == before


@pytest.mark.parametrize(
    "item",
    [
        {"op": "replace", "path": "/value"},
        {"op": "remove", "path": "/value", "value": "not removed"},
        {"op": "execute", "path": "/value", "value": "ignored"},
        {"op": "replace", "path": "", "value": {}},
    ],
)
def test_invalid_operation_shapes_are_not_executable_edits(item):
    with pytest.raises(ValueError):
        edits(item)


def test_missing_schema_root_can_be_added_but_arbitrary_new_roots_are_not_allowed():
    changed = proposal_edits.apply(
        {}, edits({"op": "replace", "path": "/value", "value": "repaired"}), Proposal
    )
    assert Proposal.model_validate(changed).value == "repaired"


def test_path_and_edit_count_are_bounded():
    candidate = {str(index): {"nested": "value"} for index in range(1000)}
    assert len(proposal_edits.paths(candidate, Proposal)) <= proposal_edits.MAX_PATHS
    with pytest.raises(ValueError):
        edits(*[{"op": "replace", "path": "/value", "value": "x"}] * 9)


def test_schema_roots_remain_editable_when_existing_paths_fill_the_catalogue():
    candidate = {str(index): {"nested": "value"} for index in range(1000)}
    allowed = proposal_edits.paths(candidate, Proposal)
    assert "/value" in allowed
    changed = proposal_edits.apply(
        candidate, edits({"op": "replace", "path": "/value", "value": "repaired"}), Proposal
    )
    assert changed["value"] == "repaired"
    assert "value" not in candidate
