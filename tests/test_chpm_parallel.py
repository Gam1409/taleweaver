"""Parallel cognition keeps bounded calls, isolated inputs and atomic publication."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import (
    actor_preparation,
    inference,
    parallel,
    parallel_budget,
    performance,
    proposal_attempt,
    rendering,
)
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.schema import KernelState, Settings, Usage
from backend.engine.chpm.state import KEY, load
from backend.models.world_entity import WorldEntity
from tests.chpm_projection_fixture import public_projection
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import chpm_world, portrait_world, update
from tests.test_chpm_json_contract import host as model_host
from tests.test_chpm_kernel import decision, observation, wire_proposal
from tests.test_chpm_reliability import Response
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import ACTION, install_roles, seed_vn

__all__ = ["chpm_world", "portrait_world"]


async def test_timing_records_match_the_exact_request_cap_and_round_trip():
    host, usage = model_host('{"value":"ok"}'), Usage()
    settings = Settings(max_calls_per_turn=25)
    for _ in range(25):
        await inference.request(host, settings, usage, "Policy", {}, Response, "proposal")
    assert len(usage.timings) == usage.calls == 25
    assert Usage.model_validate_json(usage.model_dump_json()) == usage
    with pytest.raises(RecoverableChpmError, match="budget exhausted"):
        await inference.request(host, settings, usage, "Policy", {}, Response, "proposal")
    assert len(usage.timings) == 25


async def test_concurrency_can_be_saved_without_changing_other_settings(auth_client, chpm_world):
    path = "/api/adventures/portrait-session/chpm"
    response = await auth_client.patch(path, json=update("live", npc_concurrency=2))
    assert response.status_code == 200, response.text
    first = response.json()
    changed = {**first["settings"], "npc_concurrency": 1}
    response = await auth_client.patch(
        path, json={"settings": changed, "expected_revision": first["revision"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["settings"] == changed
    assert response.json()["psychology"] == first["psychology"]
    changed["npc_concurrency"] = 5
    response = await auth_client.patch(
        path, json={"settings": changed, "expected_revision": response.json()["revision"]}
    )
    assert response.status_code == 422
    assert (await auth_client.get(path)).json()["settings"]["npc_concurrency"] == 1


@pytest.mark.parametrize("limit", [1, 2, 4])
async def test_host_preparation_stays_serial_and_inference_respects_the_selected_limit(
    monkeypatch, limit
):
    actors = [SimpleNamespace(id=str(index)) for index in range(5)]
    turn = SimpleNamespace(
        initial=KernelState(settings=Settings(npc_concurrency=limit)), decisions={}, minds={}
    )
    prepared, active, peak = [], 0, 0

    async def prepare(manager, turn, actor, observed):
        assert active == 0
        prepared.append(actor.id)
        return actor_preparation.PreparedActor(actor.id, observed, {"own": actor.id}, None, None)

    async def run(manager, turn, job):
        nonlocal active, peak
        if limit > 1:
            assert prepared == [actor.id for actor in actors]
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        assert job.supplied == {"own": job.actor_id}
        return decision(), None

    async def sequential(manager, turn, actor, observed):
        job = await prepare(manager, turn, actor, observed)
        actor_preparation.apply(turn, actor.id, await run(manager, turn, job))

    monkeypatch.setattr(actor_preparation, "prepare", prepare)
    monkeypatch.setattr(actor_preparation, "run", run)
    await parallel.prepare(
        SimpleNamespace(), turn, list(reversed(actors)), observation(), sequential
    )
    assert peak == limit
    assert list(turn.decisions) == [actor.id for actor in actors]


@pytest.mark.parametrize("cancel", [False, True])
async def test_failure_and_cancellation_publish_no_partial_results_and_leave_no_jobs(
    monkeypatch, cancel
):
    actors = [SimpleNamespace(id="a"), SimpleNamespace(id="b")]
    turn = SimpleNamespace(
        initial=KernelState(settings=Settings(npc_concurrency=2)), decisions={}, minds={}
    )
    entered, finished = asyncio.Event(), []

    async def prepare(manager, turn, actor, observed):
        return actor_preparation.PreparedActor(actor.id, observed, {}, None, None)

    async def run(manager, turn, job):
        try:
            if job.actor_id == "a":
                entered.set()
                if not cancel:
                    raise RecoverableChpmError("Rejected proposal")
                await asyncio.Event().wait()
            await entered.wait()
            return decision(), None
        finally:
            finished.append(job.actor_id)

    monkeypatch.setattr(actor_preparation, "prepare", prepare)
    monkeypatch.setattr(actor_preparation, "run", run)
    task = asyncio.create_task(
        parallel.prepare(SimpleNamespace(), turn, actors, observation(), AsyncMock())
    )
    if cancel:
        await entered.wait()
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else RecoverableChpmError):
        await task
    assert turn.decisions == {} and set(finished) == {"a", "b"}


async def test_simultaneous_invalid_proposals_share_one_retry_and_reserve_the_remaining_calls(
    monkeypatch,
):
    settings = Settings(mode="live", actor_ids=["a", "b"], agent_steps=2, max_calls_per_turn=11)
    usage = Usage(calls=1)
    host = SimpleNamespace(_chpm_turn=SimpleNamespace(names={"a": "A", "b": "B"}, decisions={}))
    barrier, proposals, repairs = asyncio.Event(), [], []

    async def request(manager, settings, usage, instruction, payload, schema, phase, **kwargs):
        inference.reserve(settings, usage, 10)
        parallel_budget.dispatched(phase)
        if phase == "proposal":
            proposals.append(performance.actor_id.get())
            if len(proposals) == 2:
                barrier.set()
            await barrier.wait()
            return Response(value="bad")
        repairs.append(performance.actor_id.get())
        await asyncio.sleep(0)
        return Response(value="valid")

    def accept(value):
        if value.value == "bad":
            raise RecoverableChpmError("Invalid source")
        return value

    async def job(actor):
        token = performance.actor_id.set(actor)
        try:
            # Two lookup rounds are already dispatched for each observer.
            for _ in range(2):
                inference.reserve(settings, usage, 10)
                parallel_budget.dispatched("agent_lookup")
            return await proposal_attempt.request(
                host, settings, usage, "Policy", {}, Response, {}, accept
            )
        finally:
            parallel_budget.finished(actor)
            performance.actor_id.reset(token)

    monkeypatch.setattr(inference, "request", request)
    with parallel_budget.reserve(["a", "b"], 3):
        results = await asyncio.gather(job("a"), job("b"), return_exceptions=True)
    assert len(repairs) == usage.proposal_repairs == 1
    assert usage.calls == 8  # perception + 4 lookups + 2 proposals + one shared retry
    assert sum(isinstance(value, Response) for value in results) == 1
    assert sum(isinstance(value, RecoverableChpmError) for value in results) == 1
    for _ in range(3):
        inference.reserve(settings, usage, 10)
    with pytest.raises(RecoverableChpmError, match="budget exhausted"):
        inference.reserve(settings, usage, 10)


@pytest.mark.parametrize("connection_policy", [False, True])
async def test_real_turn_overlaps_two_proposals_and_reloads_both_reviewed_minds(
    monkeypatch, connection_policy
):
    entered, proposals = asyncio.Event(), []

    class TwoActors(ChpmRoles):
        async def simple(self, system, payload, model, **kwargs):
            phase, supplied = kwargs.get("phase"), json.loads(payload)
            if phase == "perception":
                result = public_projection(supplied)
                for fragment in result["fragments"].values():
                    fragment["engaged"] = fragment["observers"]
                return json.dumps(result)
            if phase == "proposal":
                actor = supplied["actor_id"]
                assert ("MILA_OWN_PURPOSE" in payload) is (actor == "MILA")
                assert load(host.state).actors == {}
                proposals.append(actor)
                if len(proposals) == 2:
                    entered.set()
                await asyncio.wait_for(entered.wait(), 2)
                return json.dumps(wire_proposal())
            if phase == "validation":
                assert set(proposals) == {"LINA", "MILA"}
                assert set(supplied["contract"]) == {"LINA", "MILA"}
                passage = next(iter(supplied["passages"]))
                return json.dumps(
                    {
                        "matches": True,
                        "evidence": [
                            {"actor_id": actor, "passage_id": passage} for actor in ["LINA", "MILA"]
                        ],
                    }
                )
            return await super().simple(system, payload, model, **kwargs)

        async def stream(self, *args, **kwargs):
            assert set(proposals) == {"LINA", "MILA"}
            return await super().stream(*args, **kwargs)

    roles = TwoActors()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    from backend.engine.gameplay.manager import GameTurnManager

    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        if connection_policy:
            user.llm_settings = {
                **(user.llm_settings or {}),
                "parallel_requests": {"roles": {"complex": {"enabled": True, "max_concurrent": 2}}},
            }
        db.add(
            WorldEntity(
                id="MILA",
                session_id="session-1",
                entity_type="NPC",
                name="Mila",
                description="A traveler in a green coat.",
                current_scene_id="START",
                character="Values independence.",
                goal="MILA_OWN_PURPOSE",
            )
        )
        before = KernelState(
            settings=Settings(
                mode="live",
                actor_ids=["LINA", "MILA"],
                npc_concurrency=2,
                max_calls_per_turn=7,
                failure_policy="strict",
            )
        )
        state.entity_states = {**state.entity_states, KEY: before.model_dump()}
        await db.commit()
        host = GameTurnManager(db, "session-1", user)
        events = [event async for event in host.process_turn(ACTION)]
        assert not any(event.startswith("event: error") for event in events), "".join(events)
        await db.refresh(state)
        saved = load(state)
        assert list(saved.actors) == ["LINA", "MILA"]
        assert all(value.status == "delivered" for value in saved.actors.values())
        assert saved.usage.calls == 4
        assert len(saved.usage.timings) == 4 and saved.usage.preparation_ms >= 0
        assert {row.actor_id for row in saved.usage.timings if row.phase == "proposal"} == {
            "LINA",
            "MILA",
        }
        assert KernelState.model_validate_json(saved.model_dump_json()) == saved
        legacy = deepcopy(saved.model_dump())
        legacy["settings"].pop("npc_concurrency")
        legacy["usage"].pop("timings")
        legacy["usage"].pop("preparation_ms")
        restored = KernelState.model_validate(legacy)
        assert restored.settings.npc_concurrency == 1 and restored.usage.timings == []
        assert restored.schema_version == 6
        from backend.api.routes.adventures.chpm import Change, patch

        changed = saved.settings.model_copy(update={"npc_concurrency": 1})
        response = await patch(
            "session-1", Change(settings=changed, expected_revision=saved.revision), db, user
        )
        assert response["settings"]["npc_concurrency"] == 1
        await db.refresh(state)
        assert load(state).minds == saved.minds
        assert load(state).actors == saved.actors
