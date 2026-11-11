"""Coverage must expose omissions and keep repeated historical quotations separate."""

import pytest
from jsonschema import Draft202012Validator

from backend.engine.narrated_items import coverage, evidence, independent_state, reference_schema
from backend.engine.narrated_items.schema import ItemExtraction, SharedItemExtraction
from tests.test_narrated_items import action, fixtures


def catalog(text):
    return evidence.Catalog(text, scope="coverage-test")


def test_one_fragment_with_two_changes_cannot_report_only_one_domain_as_complete():
    source = catalog("Anna removes her shirt and spills tea on it.")
    proposal = action(destination_owner="NPC").model_dump()
    proposal["evidence"] = next(iter(source.narration_passages))
    result, audit = coverage.inspect(
        SharedItemExtraction(actions=[proposal], coverage={"c0": ["items", "conditions"]}),
        source,
        staging=False,
    )
    assert result["actions"] and audit.status == "needs_review"
    assert audit.issues == (
        {"group": "c0", "reason": "missing_proposals", "domains": ["conditions"]},
    )


@pytest.mark.parametrize("tag", ["historical", "uncertain"])
def test_non_current_fragments_cannot_silently_apply_a_completed_item_action(tag):
    text = "Anna recalls how she removed the shirt last year."
    source = catalog(text)
    raw = action(destination_owner="NPC").model_dump()
    raw["evidence"] = next(iter(source.narration_passages))
    result, audit = coverage.inspect(
        SharedItemExtraction(actions=[raw], coverage={"c0": [tag]}), source, staging=False
    )
    bound = evidence.bind(result, text, catalog=source)
    extracted, failures, _, _ = independent_state.unpack(bound, fixtures()[0])
    assert not extracted.actions and failures and audit.blocked == 1


def test_repeated_words_in_a_current_event_and_recollection_keep_distinct_occurrences():
    text = 'Anna removes her shirt.\nLater she quotes: "Anna removes her shirt."'
    source = catalog(text)
    refs = list(source.narration_passages)
    raw = action(destination_owner="NPC").model_dump()
    raw["evidence"] = refs[0]
    result, audit = coverage.inspect(
        SharedItemExtraction(actions=[raw], coverage={"c0": ["items"], "c1": ["historical"]}),
        source,
        staging=False,
    )
    assert audit.status == "complete" and audit.blocked == 0
    bound = evidence.bind(result, text, catalog=source)
    assert bound.actions[0]["evidence_span"]["start"] == 0


def test_all_fragments_remain_accounted_for_when_dense_text_needs_grouping():
    source = catalog("\n".join(f"Unchanged detail {n}." for n in range(300)))
    grouped = coverage.groups(source)
    assert len(grouped) <= coverage.MAX_GROUPS
    assert [reference for group in grouped.values() for reference in group] == source.references()


def test_empty_answer_is_complete_only_when_every_group_was_classified_unchanged():
    source = catalog("The quiet room remains unchanged.")
    _, audit = coverage.inspect(
        SharedItemExtraction(coverage={"c0": ["unchanged"]}), source, staging=False
    )
    assert audit.status == "complete"
    for raw in [None, {}, {"foreign": ["unchanged"]}]:
        _, audit = coverage.inspect(SharedItemExtraction(coverage=raw), source, staging=False)
        assert audit.status in {"unavailable", "incomplete"}


def test_wire_coverage_has_finite_required_keys_and_rejects_unknown_domains():
    source = catalog("The room remains quiet.")
    schema = reference_schema.build(ItemExtraction, source, complete=True)
    payload = ItemExtraction(coverage={"c0": ["unchanged"]}).model_dump()
    validator = Draft202012Validator(schema)
    assert validator.is_valid(payload)
    payload["coverage"] = {}
    assert not validator.is_valid(payload)
    payload["coverage"] = {"c0": ["staging"]}
    assert not validator.is_valid(payload)
