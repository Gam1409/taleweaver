"""Corrections are bounded, admitted before mutation, and preserve safe initial output."""

import asyncio
import json
import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.llm_output_errors import StructuredOutputError
from backend.engine.narrated_items import coverage, evidence, extraction_repair, extraction_request
from backend.engine.narrated_items.schema import SharedItemExtraction
from tests.test_extraction_repair import example
from tests.test_narrated_items import action, fixtures


async def request(llm, catalog, *, timeout=1, max_context=64000, accept=None):
    return await extraction_request.request(
        llm,
        "Keep existing sources and IDs.",
        json.dumps({"completed_narration": catalog.narration_passages}),
        catalog,
        game_id="TEST",
        staging=False,
        timeout=timeout,
        max_context=max_context,
        accept=accept or AsyncMock(return_value=True),
    )


def router(*outputs):
    return SimpleNamespace(
        model="offline", aexecute_complex_task=AsyncMock(side_effect=list(outputs))
    )


@pytest.mark.asyncio
async def test_genuine_omission_is_repaired_once_using_same_deadline_and_original_context():
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
    llm = router(original, patch)
    checked = await request(llm, catalog)
    assert checked.repair["status"] == "repaired"
    assert checked.extraction.condition_updates[0] == original.condition_updates[0]
    assert checked.extraction.condition_updates[1]["condition_id"] == "C_CONTENTS"
    assert llm.aexecute_complex_task.await_count == 2
    calls = llm.aexecute_complex_task.await_args_list
    assert all(call.kwargs["single_attempt"] is True for call in calls)
    assert [call.kwargs["phase"] for call in calls] == ["reconciliation", "coverage_correction"]
    assert calls[1].kwargs["max_input_chars"] == 64000
    correction = json.loads(calls[1].args[1])
    assert correction["completed_narration"] == catalog.narration_passages
    assert correction["coverage_correction"]["missing_proposals"] == {"c1": ["conditions"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [TimeoutError(), StructuredOutputError("truncated"), ValueError("invalid output")]
)
async def test_initial_uncertain_or_invalid_response_never_admits_repair(error):
    catalog, _, _ = example()
    llm = router(error)
    with pytest.raises(type(error)):
        await request(llm, catalog)
    assert llm.aexecute_complex_task.await_count == 1


@pytest.mark.asyncio
async def test_expired_schema_preparation_budget_does_not_start_initial_model_request(monkeypatch):
    catalog, original, _ = example()
    llm = router(original)
    build = extraction_request.reference_schema.build

    def delayed(*args, **kwargs):
        time.sleep(0.01)
        return build(*args, **kwargs)

    monkeypatch.setattr(extraction_request.reference_schema, "build", delayed)
    with pytest.raises(TimeoutError):
        await request(llm, catalog, timeout=0.001)
    assert llm.aexecute_complex_task.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [TimeoutError(), StructuredOutputError("bad finish"), ValueError("invalid patch")]
)
async def test_failed_correction_retains_original_safe_candidates_and_warning(error):
    catalog, original, _ = example()
    before = deepcopy(original.model_dump())
    llm = router(original, error)
    checked = await request(llm, catalog)
    assert checked.extraction is original and original.model_dump() == before
    assert checked.repair["status"] == "failed"
    assert coverage.inspect(checked.extraction, catalog, staging=False)[1].status == "needs_review"
    assert llm.aexecute_complex_task.await_count == 2


@pytest.mark.asyncio
async def test_correction_cannot_reset_timeout_or_lose_safe_output_when_deadline_expires():
    catalog, original, _ = example()
    count = 0

    async def respond(*_args, **_kwargs):
        nonlocal count
        count += 1
        await asyncio.sleep(0.03 if count == 1 else 0.1)
        return original

    llm = SimpleNamespace(model="offline", aexecute_complex_task=respond)
    start = asyncio.get_running_loop().time()
    checked = await request(llm, catalog, timeout=0.09)
    elapsed = asyncio.get_running_loop().time() - start
    assert checked.extraction is original and checked.repair["failure"] == "timeout"
    assert count == 2 and elapsed < 0.12


@pytest.mark.asyncio
async def test_oversized_correction_is_skipped_before_any_second_request():
    catalog, original, _ = example()
    llm = router(original)
    checked = await request(llm, catalog, max_context=100)
    assert checked.extraction is original
    assert checked.repair == {"status": "input_budget", "attempted": False}
    assert llm.aexecute_complex_task.await_count == 1


@pytest.mark.asyncio
async def test_correction_preparation_failure_preserves_completed_initial_response(monkeypatch):
    catalog, original, _ = example()
    llm = router(original)

    def invalid_schema(*_args):
        raise ValueError("Invalid correction schema.")

    monkeypatch.setattr(extraction_repair, "schema", invalid_schema)
    checked = await request(llm, catalog)
    assert checked.extraction is original
    assert checked.repair == {"status": "failed", "attempted": False, "failure": "unavailable"}
    assert llm.aexecute_complex_task.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_preview", [1, 2])
async def test_domain_preview_uses_the_same_absolute_deadline(blocked_preview, monkeypatch):
    catalog, original, refs = example()
    patch = extraction_repair.Additions(
        condition_updates=[
            {
                "operation": "change",
                "condition_id": "CONTENTS",
                "detail": "empty",
                "evidence": refs[1],
            }
        ]
    )
    llm = router(original, patch)
    count = 0
    budgets = []
    wait_for = asyncio.wait_for

    async def accept(*_args):
        return True

    async def expire_preview(awaitable, *, timeout):
        nonlocal count
        if getattr(awaitable, "cr_code", None) is accept.__code__:
            count += 1
            budgets.append(timeout)
            if count == blocked_preview:
                awaitable.close()
                raise TimeoutError
        return await wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(extraction_request.asyncio, "wait_for", expire_preview)
    checked = await request(llm, catalog, timeout=1, accept=accept)
    assert checked.extraction is original and checked.repair["failure"] == "timeout"
    assert llm.aexecute_complex_task.await_count == blocked_preview
    assert len(budgets) == blocked_preview and all(0 < budget <= 1 for budget in budgets)
    assert budgets == sorted(budgets, reverse=True)


@pytest.mark.asyncio
async def test_explicit_cancellation_propagates_instead_of_committing_original_turn():
    catalog, original, _ = example()
    llm = router(original, asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await request(llm, catalog)
    assert llm.aexecute_complex_task.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["repeated_confirmation", "different_domain", "dense_mixed"])
async def test_captured_overclassification_shapes_remain_honest_review(shape):
    catalog, original, _ = example()
    domain = "conditions"
    if shape == "repeated_confirmation":
        catalog = evidence.Catalog(
            "Mira rolls up the coat sleeves. Her arms remain uncovered.", scope="repeat"
        )
        refs = list(catalog.narration_passages)
        original = SharedItemExtraction(
            coverage={"c0": ["items"], "c1": ["items"]},
            actions=[
                {
                    "item_id": "COAT",
                    "source_owner": "MIRA",
                    "destination_owner": "MIRA",
                    "disposition": "worn",
                    "uncovered_regions": ["arms"],
                    "basis": "completed",
                    "evidence": refs[0],
                }
            ],
            condition_updates=[],
            scene_updates=[],
            final_frame_actions=[],
            movements=[],
        )
        domain = "items"
    elif shape == "dense_mixed":
        original.coverage["c0"] = ["items", "conditions"]
        original.coverage["c1"] = ["unchanged"]
        domain = "items"
    group = "c0" if shape == "dense_mixed" else "c1"
    patch = extraction_repair.Additions(
        classification_review=[{"group": group, "domain": domain, "reason": "different_domain"}]
    )
    llm = router(original, patch)
    checked = await request(llm, catalog)
    assert checked.extraction is original and checked.repair["status"] == "classification_review"
    assert coverage.inspect(checked.extraction, catalog, staging=False)[1].status == "needs_review"


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["transfer", "intent", "restoration"])
async def test_captured_complete_shapes_keep_one_initial_request(shape):
    catalog = evidence.Catalog("The scarf remains where it is.", scope=shape)
    original = SharedItemExtraction(
        coverage={"c0": ["unchanged"]},
        actions=[],
        condition_updates=[],
        scene_updates=[],
        final_frame_actions=[],
        movements=[],
    )
    llm = router(original)
    checked = await request(llm, catalog)
    assert checked.extraction is original and checked.repair is None
    assert llm.aexecute_complex_task.await_count == 1


@pytest.mark.asyncio
async def test_runtime_applies_verified_original_transfer_after_correction_failure(monkeypatch):
    from backend.engine.narrated_items import runtime

    actors, snapshot = fixtures()
    manager = SimpleNamespace(
        avatar=SimpleNamespace(**actors["__player__"]),
        state=SimpleNamespace(entity_states={}, session_id="TEST", current_scene_id="ROOM"),
        game_id="TEST",
        user=SimpleNamespace(),
        db=SimpleNamespace(get=AsyncMock(return_value=None)),
        _vn_player_message_id="TURN",
    )
    text = action().evidence + " The bottle is empty."
    raw = SharedItemExtraction(
        coverage={"c0": ["items"], "c1": ["conditions"]},
        actions=[action().model_dump()],
        condition_updates=[],
        scene_updates=[],
        final_frame_actions=[],
        movements=[],
    )
    llm = router(raw, StructuredOutputError("bad finish"))
    monkeypatch.setattr(
        runtime,
        "session_objects",
        AsyncMock(return_value=[SimpleNamespace(id="NPC", entity_type="NPC", age_years=30)]),
    )
    monkeypatch.setattr(runtime, "actor_records", lambda *_: actors)
    monkeypatch.setattr(runtime, "possession_snapshot", lambda *_: snapshot)
    monkeypatch.setattr(runtime, "detail_settings", lambda *_: {"detailed": True})
    monkeypatch.setattr(runtime, "release_for_model", AsyncMock())
    monkeypatch.setattr(runtime.scene_continuity, "prepare", AsyncMock(return_value={}))
    monkeypatch.setattr(runtime.narrated_movement, "prepare", AsyncMock(return_value={}))
    monkeypatch.setattr(runtime.GameMasterLLM, "for_role", lambda *_: llm)
    messages = await runtime.reconcile_items(manager, text, completed=True, resolution="")
    assert manager.avatar.inventory[0]["id"] == "SHIRT"
    saved = manager.state.entity_states[runtime.KEY]
    assert saved["status"] == "needs_review" and saved["coverage_repair"]["status"] == "failed"
    assert saved["accepted"][0]["item"]["id"] == "SHIRT"
    assert saved["extraction_coverage"]["issues"][0]["group"] == "c1"
    assert any("not fully accounted" in message for message in messages)
