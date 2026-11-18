"""Correction admission includes provider schema overhead and preserves proof context."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from backend.core.llm_structured_execution import require_input_budget
from backend.engine.narrated_items import correction_input, extraction_repair, extraction_request
from backend.engine.narrated_items.schema import SharedItemExtraction
from tests.test_extraction_repair import example
from tests.test_llm_structured_single_attempt import router


@pytest.mark.parametrize("mode", ["prompt", "json_object", "json_schema"])
async def test_large_visual_context_cannot_prevent_an_independent_state_correction(
    monkeypatch, mode
):
    catalog, original, refs = example()
    patch = extraction_repair.Additions(
        condition_updates=[
            {
                "operation": "change",
                "condition_id": "C_CONTENTS",
                "detail": "empty",
                "evidence": refs[1],
            }
        ]
    )
    llm = router(monkeypatch, mode)
    llm.model = "local-model"
    payload = {
        "completed_narration": catalog.narration_passages,
        "actors": {"NPC": {"name": "Alex"}},
        "owners": {"BOTTLE": "NPC"},
        "physical_conditions": {"C_CONTENTS": {"target_id": "BOTTLE", "detail": "full"}},
        "independent_state_scope": {"blocked_subject_ids": ["OTHER"]},
        "scene_continuity": {
            "scene_id": "ROOM",
            "public_subjects": [{"id": "BOTTLE", "name": "Bottle"}],
        },
        "scene_staging": {
            "scene_id": "ROOM",
            "owned_items": [{"item_id": "BOTTLE", "owner_id": "NPC"}],
            "irrelevant_visual_detail": "x" * 52000,
        },
    }
    saved = deepcopy(payload)
    instructions = "Preserve source, identity and ownership rules. " * 120
    calls = []
    failures = []
    describe = extraction_request.describe_failure

    def capture_failure(exc):
        failures.append(repr(exc))
        return describe(exc)

    monkeypatch.setattr(extraction_request, "describe_failure", capture_failure)

    async def respond(system, content, schema, model, **kwargs):
        calls.append((system, content, kwargs))
        if schema is SharedItemExtraction:
            return original
        request = llm._build_structured_request(
            system, content, schema, model, response_schema=kwargs.get("response_schema")
        )
        require_input_budget(request.kwargs, kwargs["max_input_chars"])
        corrected_context = json.loads(content)
        for key in (
            "completed_narration",
            "actors",
            "owners",
            "physical_conditions",
            "independent_state_scope",
        ):
            assert corrected_context[key] == saved[key]
        assert corrected_context["scene_continuity"] == saved["scene_continuity"]
        assert (
            corrected_context["scene_staging"]["owned_items"]
            == saved["scene_staging"]["owned_items"]
        )
        return patch

    monkeypatch.setattr(llm, "aexecute_complex_task", respond)

    async def accept(*_args):
        return True

    checked = await extraction_request.request(
        llm,
        instructions,
        json.dumps(payload),
        catalog,
        game_id="TEST",
        staging=False,
        timeout=3,
        max_context=64000,
        accept=accept,
    )

    assert checked.repair["status"] == "repaired", failures
    assert len(checked.extraction.condition_updates) == 2
    assert checked.extraction.condition_updates[0] == original.condition_updates[0]
    assert len(calls) == 2 and payload == saved
    assert calls[1][2]["max_input_chars"] == 64000


@pytest.mark.parametrize(
    "domain,disabled", [("conditions", "actions"), ("items", "condition_updates")]
)
def test_correction_schema_only_allows_the_missing_domain(domain, disabled):
    catalog, _, refs = example()
    contract = extraction_repair.schema(catalog, domains={domain})
    validator = Draft202012Validator(contract)
    assert contract["properties"][disabled]["maxItems"] == 0
    assert validator.is_valid({"actions": [], "condition_updates": [], "classification_review": []})
    assert not validator.is_valid(
        {
            "actions": [],
            "condition_updates": [],
            "classification_review": [
                {
                    "group": "c1",
                    "domain": "items" if domain == "conditions" else "conditions",
                    "reason": "uncertain",
                }
            ],
        }
    )
    assert "NarrationEvidenceReference" in contract["$defs"]
    assert contract["$defs"]["NarrationEvidenceReference"]["enum"]
    assert refs[1] in contract["$defs"]["NarrationEvidenceReference"]["enum"]


async def test_prepared_size_check_does_not_dispatch_or_log_a_model_call(monkeypatch):
    from unittest.mock import Mock

    from tests.test_llm_structured_input_budget import input_size

    catalog, _, _ = example()
    llm = router(monkeypatch, "json_schema")
    llm.model = "local-model"
    schema = extraction_repair.schema(catalog, domains={"conditions"})
    emit = Mock(side_effect=AssertionError("Preflight must not emit a contract for a model call."))
    monkeypatch.setattr("backend.core.llm_structured_output.trace", emit)
    size = llm.structured_input_characters(
        "policy", "{}", extraction_repair.Additions, llm.model, response_schema=schema
    )
    request = llm._build_structured_request(
        "policy",
        "{}",
        extraction_repair.Additions,
        llm.model,
        response_schema=schema,
        emit_contract=False,
    )
    assert size == input_size(request.kwargs)
    emit.assert_not_called()


@pytest.mark.parametrize("mode", ["prompt", "json_object", "json_schema"])
def test_correction_input_exact_limit_and_irreducible_context(monkeypatch, mode):
    catalog, _, _ = example()
    llm = router(monkeypatch, mode)
    llm.model = "local-model"
    schema = extraction_repair.schema(catalog, domains={"conditions"})
    context = {"actors": {"NPC": {"name": "Alex"}}, "completed_narration": "The bottle is empty."}
    content = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    size = llm.structured_input_characters(
        "policy", content, extraction_repair.Additions, llm.model, response_schema=schema
    )
    accepted = correction_input.prepare(llm, "policy", context, schema, size)
    assert accepted is not None and accepted.input_chars == size
    assert not accepted.focused
    assert correction_input.prepare(llm, "policy", context, schema, size - 1) is None
    assert json.loads(accepted.content) == context


async def test_irreducible_correction_preserves_initial_result_without_an_extra_call():
    from types import SimpleNamespace

    catalog, original, _ = example()
    calls = []

    async def respond(*args, **kwargs):
        calls.append(kwargs)
        return original

    async def accept(*_args):
        return True

    llm = SimpleNamespace(model="local-model", aexecute_complex_task=respond)
    result = await extraction_request.request(
        llm,
        "policy",
        json.dumps({"actors": {"NPC": {"name": "Alex"}}}),
        catalog,
        game_id="TEST",
        staging=False,
        timeout=3,
        max_context=1,
        accept=accept,
    )
    assert result.extraction is original
    assert result.repair == {"status": "input_budget", "attempted": False}
    assert len(calls) == 1
