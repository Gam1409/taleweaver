"""Correction values survive selected native schemas, HTTP and complete input admission."""

import json

import httpx
import pytest
from jsonschema import Draft202012Validator

from backend.core.llm_schema_values import json_equal
from backend.engine.chpm import json_contract
from backend.engine.chpm.proposal_edits import Corrections
from tests.test_llm_schema_any_json import PATHS, VALUES, correction, object_default_decoder
from tests.test_llm_structured_input_budget import input_size
from tests.test_llm_structured_single_attempt import completion, mock_http, router


@pytest.mark.parametrize("value", VALUES)
async def test_native_wire_can_represent_each_value_that_the_correction_owner_accepts(
    monkeypatch, value
):
    sample = correction(value)

    async def respond(request):
        body = json.loads(request.content)
        schema = body["response_format"]["json_schema"]["schema"]
        assert Draft202012Validator(object_default_decoder(schema)).is_valid(sample)
        return httpx.Response(
            200,
            json=completion(json.dumps(sample, ensure_ascii=False)),
            request=request,
        )

    llm = router(monkeypatch, "json_schema")
    seen = mock_http(monkeypatch, respond)
    result = await llm.aexecute_complex_task(
        "Correct only the supported field.",
        "Preserve the other proposed fields.",
        Corrections,
        "local-model",
        response_schema=json_contract.response_schema(Corrections, {"path": PATHS}),
        single_attempt=True,
    )

    assert len(seen) == 1
    assert json_equal(result.edits[0].value, value)


@pytest.mark.parametrize("value_present", [False, True])
async def test_remove_retains_omitted_or_explicit_null_value_semantics(monkeypatch, value_present):
    edit = {"op": "remove", "path": PATHS[2], **({"value": None} if value_present else {})}
    sample = {"edits": [edit]}

    async def respond(request):
        schema = json.loads(request.content)["response_format"]["json_schema"]["schema"]
        assert Draft202012Validator(object_default_decoder(schema)).is_valid(sample)
        return httpx.Response(200, json=completion(json.dumps(sample)), request=request)

    seen = mock_http(monkeypatch, respond)
    result = await router(monkeypatch, "json_schema").aexecute_complex_task(
        "Correct the field.",
        "Remove that optional field.",
        Corrections,
        "local-model",
        single_attempt=True,
    )

    assert len(seen) == 1
    assert result.edits[0].value is None
    assert ("value" in result.edits[0].model_fields_set) is value_present


@pytest.mark.parametrize("difference", [-1, 0])
async def test_explicit_json_value_schema_is_included_in_the_exact_prepared_input_budget(
    monkeypatch, difference
):
    sample = correction("A corrected reason.")
    raw = json_contract.response_schema(Corrections, {"path": PATHS})
    llm = router(monkeypatch, "json_schema")
    prepared = llm._build_structured_request(
        "Correct the field.",
        "Preserve other fields.",
        Corrections,
        "local-model",
        response_schema=raw,
    )
    measured = input_size(prepared.kwargs)

    async def respond(request):
        assert input_size(json.loads(request.content)) == measured
        return httpx.Response(200, json=completion(json.dumps(sample)), request=request)

    seen = mock_http(monkeypatch, respond)
    task = llm.aexecute_complex_task(
        "Correct the field.",
        "Preserve other fields.",
        Corrections,
        "local-model",
        response_schema=raw,
        single_attempt=True,
        max_input_chars=measured + difference,
    )
    if difference < 0:
        with pytest.raises(ValueError, match="input exceeds"):
            await task
        assert seen == []
        return
    result = await task
    assert len(seen) == 1
    assert result == Corrections.model_validate(sample)
