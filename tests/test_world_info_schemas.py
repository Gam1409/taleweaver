"""Request validation preserves immutable evidence and explicit recipient boundaries."""

import copy

import pytest

from backend.engine.world_info.schemas import ControlVersion, EntryUpdate, Publish, Version


def update_body():
    return {
        "version": 1,
        "title": "Coastal history",
        "summary": "A source-backed account.",
        "kind": "reported_claim",
        "audience": "narrator_only",
        "known_by": [],
        "tags": ["#harbour"],
        "relations": [],
        "facts": [{"id": "fact-1", "text": "The beacon was rebuilt."}],
    }


@pytest.mark.parametrize("schema,key", [(Version, "version"), (ControlVersion, "control_version")])
@pytest.mark.parametrize("value", [0, -1, True, "1", 1.0])
def test_compare_and_set_versions_are_positive_strict_integers(schema, key, value):
    with pytest.raises(ValueError):
        schema.model_validate({key: value})
    assert getattr(schema.model_validate({key: 1}), key) == 1


@pytest.mark.parametrize("field", ["evidence", "original_text", "edited", "source_hash"])
def test_fact_updates_cannot_replace_source_evidence_or_authorship(field):
    body = update_body()
    body["facts"][0][field] = "cannot replace"
    with pytest.raises(ValueError):
        EntryUpdate.model_validate(body)


@pytest.mark.parametrize(
    "audience,known_by,valid",
    [
        ("narrator_only", [], True),
        ("common_knowledge", [], True),
        ("restricted", ["NPC_1"], True),
        ("restricted", [], False),
        ("narrator_only", ["NPC_1"], False),
        ("common_knowledge", ["NPC_1"], False),
        ("restricted", ["NPC_1", "NPC_1"], False),
    ],
)
def test_recipient_scope_is_explicit_and_distinct(audience, known_by, valid):
    body = update_body() | {"audience": audience, "known_by": known_by}
    if valid:
        assert EntryUpdate.model_validate(body).known_by == known_by
    else:
        with pytest.raises(ValueError):
            EntryUpdate.model_validate(body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", " "),
        ("facts", []),
        ("tags", ["#same", "#same"]),
        ("tags", ["bad\x00tag"]),
        ("tags", [" "]),
        ("tags", ["x" * 49]),
        ("relations", [{"target_id": "other", "kind": "related"}] * 2),
    ],
)
def test_invalid_edit_fields_fail_without_coercion_or_truncation(field, value):
    with pytest.raises(ValueError):
        EntryUpdate.model_validate(update_body() | {field: value})


def test_duplicate_fact_ids_are_rejected_and_exact_fact_limit_is_retained():
    body = update_body()
    body["facts"] = body["facts"] * 2
    with pytest.raises(ValueError):
        EntryUpdate.model_validate(body)
    body["facts"] = [{"id": f"f{i}", "text": "t" * 500} for i in range(8)]
    assert len(EntryUpdate.model_validate(body).facts) == 8
    body["facts"].append({"id": "ninth", "text": "extra"})
    with pytest.raises(ValueError):
        EntryUpdate.model_validate(body)


def test_publish_selection_one_to_256_distinct_versions():
    body = {
        "revision_id": "revision",
        "source_version": 1,
        "entries": [{"id": f"e{i}", "version": 1} for i in range(256)],
    }
    assert len(Publish.model_validate(body).entries) == 256
    for invalid in [
        [],
        [body["entries"][0]] * 2,
        body["entries"] + [{"id": "extra", "version": 1}],
    ]:
        with pytest.raises(ValueError):
            Publish.model_validate(body | {"entries": invalid})
    changed = copy.deepcopy(body)
    changed["entries"][0]["version"] = True
    with pytest.raises(ValueError):
        Publish.model_validate(changed)


def test_resolving_retained_recipients_requires_explicit_distinct_selected_ids():
    body = update_body() | {"audience": "restricted", "known_by": ["NPC_1", "NPC_2"]}
    assert EntryUpdate.model_validate(body).resolve_known_by == []
    assert EntryUpdate.model_validate(body | {"resolve_known_by": ["NPC_1"]}).resolve_known_by == [
        "NPC_1"
    ]
    for invalid in [["unknown"], ["NPC_1", "NPC_1"]]:
        with pytest.raises(ValueError):
            EntryUpdate.model_validate(body | {"resolve_known_by": invalid})
