"""Reviewed VN turns commit integrated decisions and private notes atomically."""

import asyncio
import json
from copy import deepcopy

import pytest

from backend.engine.chpm.state import load
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_native_notebook_loop import call, turn
from tests.test_chpm_native_notebook_turn import NativeRoles, initial_payload, tool_results
from tests.test_chpm_notebook_turn import ACTION, NOTE, configure, install, stored
from tests.test_chpm_turn import ChpmRoles


class IntegratedRoles(NativeRoles):
    async def native(self, messages, tools, model, **kwargs):
        if kwargs["phase"] != "integrated_decision":
            return await super().native(messages, tools, model, **kwargs)
        body = initial_payload(messages)
        self.native_requests.append((deepcopy(messages), deepcopy(tools), kwargs))
        self.chpm_calls.append(kwargs["phase"])
        if not tool_results(messages):
            return self.write_and_read(body)
        if self.fault == "timeout":
            raise TimeoutError("Offline integrated timeout after staged write")
        if self.fault == "cancel":
            self.paused.set()
            await asyncio.Event().wait()
        if self.fault == "truncation":
            return turn(call("cutoff", "submit_decision", {}), finish_reason="length")
        raw = await ChpmRoles.simple(self, "", json.dumps(body), model, phase="proposal")
        self.chpm_calls.pop()  # Reuse the fixture builder; this was no extra model call.
        return turn(call("decision", "submit_decision", json.loads(raw)))


@pytest.mark.parametrize("fault", [None, "review", "timeout"])
async def test_integrated_turn_respects_publication_and_notebook_transaction(monkeypatch, fault):
    roles = IntegratedRoles(fault)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db, workflow="integrated", max_input_chars=48000)
        before = load(state)
        manager, events = await run(db, user, ACTION)
        await db.refresh(state)
        if fault:
            assert any(chunk.startswith("event: error") for chunk in events), "".join(events)
            assert not any(chunk.startswith("event: chunk") for chunk in events)
            assert load(state) == before
            assert not await stored(db)
            return
        assert any(chunk.startswith("event: final") for chunk in events), "".join(events)
        saved = load(manager.state)
        assert saved.usage.workflow == "integrated"
        assert saved.usage.calls == 4
        assert roles.chpm_calls == [
            "perception",
            "integrated_decision",
            "integrated_decision",
            "validation",
        ]
        documents = await stored(db)
        assert len(documents) == 1 and json.loads(documents[0].payload) == {"private": NOTE}
        assert NOTE not in json.dumps(saved.model_dump())
        assert NOTE not in json.dumps(roles.prompts, default=str)
        assert saved.actors["LINA"].status == "delivered"


async def test_combined_context_over_budget_rejects_before_model_dispatch(monkeypatch):
    roles = IntegratedRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db, workflow="integrated", max_input_chars=8000)
        before = load(state)
        _, events = await run(db, user, ACTION)
        assert any(chunk.startswith("event: error") for chunk in events)
        assert not any(chunk.startswith("event: chunk") for chunk in events)
        assert roles.native_requests == []
        await db.refresh(state)
        assert load(state) == before and not await stored(db)


async def test_cancelled_integrated_round_cannot_publish_staged_notes(monkeypatch):
    roles = IntegratedRoles("cancel")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db, workflow="integrated", max_input_chars=48000)
        before = load(state)
        task = asyncio.create_task(run(db, user, ACTION))
        await asyncio.wait_for(roles.paused.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await db.refresh(state)
        assert load(state) == before and not await stored(db)
        assert len(roles.native_requests) == 2


async def test_truncated_submission_cannot_publish_staged_notes_or_trigger_repair(monkeypatch):
    roles = IntegratedRoles("truncation")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db, workflow="integrated", max_input_chars=48000)
        before = load(state)
        _, events = await run(db, user, ACTION)
        assert any(chunk.startswith("event: error") for chunk in events)
        await db.refresh(state)
        assert load(state) == before and not await stored(db)
        assert len(roles.native_requests) == 2
        assert "proposal_repair" not in roles.chpm_calls
