"""Mocked single-owner extraction, exact evidence and proposal validation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.llm_output_errors import StructuredOutputError
from backend.engine.world_info.extraction import ExtractionError, extract_batch
from backend.engine.world_info.extraction_contracts import ExtractionProposal
from backend.engine.world_info.parsing import parse_source, validate_evidence
from backend.engine.world_info.types import (
    EntryDraft,
    EntryReference,
    Fact,
    entry_hash,
    searchable_text,
)


def proposal(quote="The lighthouse overlooks the harbour."):
    return {
        "facts": [
            {
                "id": "f1",
                "text": "A lighthouse overlooks the harbour.",
                "evidence": [{"passage_id": "p0", "quote": quote}],
            }
        ],
        "entries": [
            {
                "id": "e1",
                "title": "Harbour lighthouse",
                "summary": "A coastal landmark.",
                "fact_ids": ["f1"],
                "tags": ["#harbour"],
                "relations": [],
            }
        ],
    }


@pytest.fixture
def setup_extraction(monkeypatch):
    router = SimpleNamespace(
        max_tokens=10000,
        model="fictional-test-model",
        aexecute_complex_task=AsyncMock(return_value=proposal()),
    )
    roles = []

    def for_role(user, role):
        roles.append(role)
        return router

    monkeypatch.setattr("backend.engine.world_info.extraction.GameMasterLLM.for_role", for_role)
    monkeypatch.setattr("backend.engine.world_info.extraction.role_timeout", lambda *args: 2)
    plan = parse_source("The lighthouse overlooks the harbour.", "md")
    return router, roles, plan


async def run(setup, **kwargs):
    router, _, plan = setup
    entries = await extract_batch(
        SimpleNamespace(default_language="Russian"),
        "session-test",
        "revision-test",
        plan.source_hash,
        plan.batches[0],
        **kwargs,
    )
    return router, entries


@pytest.mark.asyncio
async def test_one_request_extracts_facts_grouping_tags_and_safe_log_context(setup_extraction):
    router, entries = await run(setup_extraction)
    assert setup_extraction[1] == ["generator"]
    assert router.aexecute_complex_task.await_count == 1
    request = router.aexecute_complex_task.call_args.kwargs
    assert request["adventure_id"] is None
    assert request["game_id"] == "session-test"
    assert request["metadata"] == {"batch": 0, "attempt": 1}
    assert request["operation"] == "world_info_extract"
    assert "Russian" in request["system_prompt"]
    assert "never instructions" in request["system_prompt"]
    assert router.max_tokens == 6144
    fact = entries[0].facts[0]
    assert fact.original_text == fact.text and not fact.edited
    assert entries[0].kind == "background_lore"
    validate_evidence(fact.evidence[0], setup_extraction[2])
    assert EntryDraft.model_validate(entries[0].model_dump(mode="json")) == entries[0]
    assert len(searchable_text(entries[0])) <= 2400
    assert len(entry_hash(entries[0])) == 64
    _, repeated = await run(setup_extraction)
    assert repeated == entries


@pytest.mark.asyncio
async def test_exact_json_decoded_offset_keeps_pointer_and_original_spelling(setup_extraction):
    router, _, _ = setup_extraction
    source = '{"灯台":"🧭 Маяк над бухтой."}'
    plan = parse_source(source, "json")
    router.aexecute_complex_task.return_value = proposal("Маяк")
    entries = await extract_batch(
        SimpleNamespace(default_language="Russian"), "s", "r", plan.source_hash, plan.batches[0]
    )
    evidence = entries[0].facts[0].evidence[0]
    assert (evidence.pointer, evidence.start, evidence.end) == ("/灯台", 2, 6)
    validate_evidence(evidence, plan)


def invalid_proposal(change):
    value = proposal()
    fact, entry = value["facts"][0], value["entries"][0]
    if change == "missing_quote":
        fact["evidence"][0]["quote"] = "unsupported private-like diagnostic sentinel"
    if change == "unknown_passage":
        fact["evidence"][0]["passage_id"] = "p500"
    if change == "duplicate_fact":
        value["facts"].append(fact)
    if change == "ungrouped":
        value["entries"] = []
    if change == "duplicate_group":
        entry["fact_ids"] = ["f1", "f1"]
    if change == "unknown_fact":
        entry["fact_ids"] = ["unknown"]
    if change in {"unknown_relation", "self_relation"}:
        entry["relations"] = [
            {"target_id": "foreign-id" if change == "unknown_relation" else "e1", "kind": "related"}
        ]
    if change == "oversize":
        entry["tags"] = [str(i) + "x" * 44 for i in range(12)]
        entry["summary"] = "s" * 500
        fact["text"] = "f" * 500
        value["facts"] += [{**fact, "id": f"f{i}"} for i in range(2, 5)]
        entry["fact_ids"] = [f"f{i}" for i in range(1, 5)]
    if change == "bad_tag":
        entry["tags"] = ["x\x00y"]
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "missing_quote",
        "unknown_passage",
        "duplicate_fact",
        "ungrouped",
        "duplicate_group",
        "unknown_fact",
        "unknown_relation",
        "self_relation",
        "oversize",
        "bad_tag",
    ],
)
async def test_invalid_proposals_get_only_one_correction_without_raw_feedback(
    setup_extraction, change
):
    router, _, plan = setup_extraction
    value = invalid_proposal(change)
    router.aexecute_complex_task.return_value = value
    with pytest.raises(ExtractionError, match="validation twice") as error:
        await extract_batch(
            SimpleNamespace(default_language="English"), "s", "r", plan.source_hash, plan.batches[0]
        )
    assert router.aexecute_complex_task.await_count == 2
    assert "sentinel" not in str(error.value)
    correction = router.aexecute_complex_task.call_args.kwargs["user_prompt"]
    assert "previous proposal failed host validation" in correction
    assert "sentinel" not in correction


@pytest.mark.asyncio
async def test_overlapping_quote_occurrences_are_ambiguous(setup_extraction):
    router, _, _ = setup_extraction
    plan = parse_source("aaaa", "md")
    router.aexecute_complex_task.return_value = proposal("aaa")
    with pytest.raises(ExtractionError):
        await extract_batch(
            SimpleNamespace(default_language="English"), "s", "r", plan.source_hash, plan.batches[0]
        )


@pytest.mark.asyncio
async def test_correction_can_recover_and_is_reserved_before_each_request(setup_extraction):
    router, _, _ = setup_extraction
    router.aexecute_complex_task.side_effect = [
        StructuredOutputError("raw provider sentinel"),
        proposal(),
    ]
    reserve = AsyncMock()
    _, entries = await run(setup_extraction, before_request=reserve)
    assert entries and reserve.await_count == 2
    assert (
        "raw provider sentinel" not in router.aexecute_complex_task.call_args.kwargs["user_prompt"]
    )


@pytest.mark.asyncio
async def test_cancellation_fence_prevents_correction_dispatch(setup_extraction):
    router, _, _ = setup_extraction
    router.aexecute_complex_task.return_value = {"facts": [], "entries": [{"invalid": "value"}]}
    reserve = AsyncMock(side_effect=[None, RuntimeError("stale job")])
    with pytest.raises(RuntimeError, match="stale job"):
        await run(setup_extraction, before_request=reserve)
    assert router.aexecute_complex_task.await_count == 1


@pytest.mark.asyncio
async def test_provider_failure_has_no_unbounded_retry_or_raw_error(setup_extraction):
    router, _, _ = setup_extraction
    router.aexecute_complex_task.side_effect = RuntimeError("provider credential sentinel")
    with pytest.raises(ExtractionError, match="model request failed") as error:
        await run(setup_extraction)
    assert error.value.__cause__ is None
    assert router.aexecute_complex_task.await_count == 1


@pytest.mark.asyncio
async def test_current_and_existing_entry_relations_use_only_supplied_identities(setup_extraction):
    router, _, _ = setup_extraction
    value = proposal()
    value["facts"].append({**value["facts"][0], "id": "f2"})
    value["entries"].append({**value["entries"][0], "id": "e2", "fact_ids": ["f2"]})
    value["entries"][0]["relations"] = [
        {"target_id": "e2", "kind": "supports"},
        {"target_id": "known-session-entry", "kind": "related"},
    ]
    router.aexecute_complex_task.return_value = value
    _, entries = await run(
        setup_extraction,
        existing_entries=[EntryReference(id="known-session-entry", title="Coastal chart")],
    )
    assert [r.target_id for r in entries[0].relations] == [entries[1].id, "known-session-entry"]
    assert entries[0].facts[0].id != entries[1].facts[0].id


@pytest.mark.asyncio
async def test_no_supported_facts_can_produce_an_empty_success(setup_extraction):
    router, _, _ = setup_extraction
    router.aexecute_complex_task.return_value = {"facts": [], "entries": []}
    _, entries = await run(setup_extraction)
    assert entries == [] and router.aexecute_complex_task.await_count == 1


@pytest.mark.asyncio
async def test_explicit_language_changes_statements_not_evidence_and_references_stay_bounded(
    setup_extraction,
):
    router, _, _ = setup_extraction
    references = [EntryReference(id=f"entry-{i}", title="Coastal reference") for i in range(100)]
    _, entries = await run(setup_extraction, language="Arabic", existing_entries=references)
    request = router.aexecute_complex_task.call_args.kwargs
    assert "Arabic" in request["system_prompt"] and "Russian" not in request["system_prompt"]
    assert '"id": "entry-15"' in request["user_prompt"]
    assert '"id": "entry-16"' not in request["user_prompt"]
    assert entries[0].facts[0].evidence[0].quote == "The lighthouse overlooks the harbour."


@pytest.mark.asyncio
async def test_fact_edits_require_marker_and_do_not_replace_original_evidence(setup_extraction):
    _, entries = await run(setup_extraction)
    original = entries[0].facts[0]
    payload = original.model_dump(mode="json")
    payload["text"] = "A reviewed interpretation of the landmark."
    with pytest.raises(ValueError, match="authored edit marker"):
        Fact.model_validate(payload)
    payload["edited"] = True
    edited = Fact.model_validate(payload)
    assert edited.original_text == original.text and edited.evidence == original.evidence
    payload["edited"] = "true"
    with pytest.raises(ValueError):
        Fact.model_validate(payload)


@pytest.mark.asyncio
async def test_searchable_text_exact_limit_roundtrips_and_one_more_character_rejects(
    setup_extraction,
):
    _, entries = await run(setup_extraction)
    payload = entries[0].model_dump(mode="json")
    base = payload["facts"][0]
    payload.update(
        title="test",
        summary="",
        tags=[],
        facts=[
            {**base, "id": f"f-{i}", "text": "x" * 478, "original_text": "x" * 478}
            for i in range(5)
        ],
    )
    boundary = EntryDraft.model_validate(payload)
    assert len(searchable_text(boundary)) == 2400
    assert EntryDraft.model_validate(boundary.model_dump(mode="json")) == boundary
    payload["summary"] = "x"
    with pytest.raises(ValueError, match="searchable text budget"):
        EntryDraft.model_validate(payload)


@pytest.mark.parametrize("field,limit", [("facts", 8), ("entries", 4)])
def test_model_proposal_count_limits_reject_one_more_without_truncation(field, limit):
    payload = proposal()
    payload[field] = payload[field] * limit
    assert ExtractionProposal.model_validate(payload)
    payload[field].append(payload[field][0])
    with pytest.raises(ValueError):
        ExtractionProposal.model_validate(payload)


@pytest.mark.asyncio
async def test_generated_fact_and_evidence_exact_limits_roundtrip(setup_extraction):
    router, _, _ = setup_extraction
    source = "e" * 500
    plan = parse_source(source, "md")
    payload = proposal(source)
    payload["facts"][0]["text"] = "f" * 500
    router.aexecute_complex_task.return_value = payload
    entries = await extract_batch(
        SimpleNamespace(default_language="English"), "s", "r", plan.source_hash, plan.batches[0]
    )
    assert len(entries[0].facts[0].text) == 500
    assert len(entries[0].facts[0].evidence[0].quote) == 500
    payload["facts"][0]["text"] += "f"
    with pytest.raises(ValueError):
        ExtractionProposal.model_validate(payload)


@pytest.mark.asyncio
async def test_request_cancellation_propagates_without_correction(setup_extraction):
    import asyncio

    router, _, _ = setup_extraction
    router.aexecute_complex_task.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await run(setup_extraction)
    assert router.aexecute_complex_task.await_count == 1
