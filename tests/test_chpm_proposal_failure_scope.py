"""Completed proposal rejection is local; transport, cancellation and host faults are not."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import actor_preparation, inference, parallel, proposal_attempt
from backend.engine.chpm.errors import (
    ChpmError,
    InferenceUnavailableError,
    ProposalRejectedError,
    RecoverableChpmError,
)
from backend.engine.chpm.runtime import Turn
from backend.engine.chpm.schema import KernelState, Settings
from tests.test_chpm_kernel import decision, observation
from tests.test_chpm_reliability import Response


def turn():
    result = Turn(
        KernelState(settings=Settings(mode="live", actor_ids=["npc", "peer"], npc_concurrency=2)),
        "input",
    )
    result.names = {"npc": "Rin", "peer": "Mila"}
    result.initial.recovery.gap_cursors = {"npc": 2}
    result.gap_cursors = {"npc": 9}
    return result


def install(monkeypatch, errors):
    async def prepare(_manager, value, actor, observed):
        value.memories[actor.id] = []
        value.agendas[actor.id] = []
        value.causal_threads[actor.id] = []
        value.semantic_hits[actor.id] = []
        return actor_preparation.PreparedActor(actor.id, observed, {}, None, None)

    async def run(_manager, _turn, job):
        await asyncio.sleep(0)
        if job.actor_id in errors:
            raise errors[job.actor_id]
        return decision().model_copy(update={"actor_id": job.actor_id}), None

    monkeypatch.setattr(actor_preparation, "prepare", prepare)
    monkeypatch.setattr(actor_preparation, "run", run)


async def dispatch(value):
    await parallel.prepare(
        SimpleNamespace(),
        value,
        [SimpleNamespace(id="npc"), SimpleNamespace(id="peer")],
        observation(),
        AsyncMock(),
    )


async def test_local_rejection_discards_only_its_drafts_and_restores_its_gap_cursor(monkeypatch):
    value = turn()
    install(monkeypatch, {"npc": ProposalRejectedError("Invalid intention")})
    await dispatch(value)
    assert set(value.decisions) == {"peer"}
    assert value.names == {"peer": "Mila"} and value.deferred_names == {"npc": "Rin"}
    assert value.gap_cursors == {"npc": 2}
    assert set(value.usage.actor_failures) == {"npc"}
    for field in ("memories", "agendas", "causal_threads", "semantic_hits"):
        assert "npc" not in getattr(value, field)


@pytest.mark.parametrize(
    "error_type", [InferenceUnavailableError, ChpmError, RecoverableChpmError, RuntimeError]
)
@pytest.mark.parametrize("bad", ["npc", "peer"])
async def test_shared_failure_is_not_downgraded_to_a_rejected_intention(
    monkeypatch, error_type, bad
):
    value = turn()
    error = error_type("Shared failure")
    install(monkeypatch, {bad: error})
    with pytest.raises(error_type) as caught:
        await dispatch(value)
    assert caught.value is error
    assert not value.decisions and not value.usage.actor_failures


async def test_host_fault_has_priority_over_a_separate_local_rejection(monkeypatch):
    value = turn()
    install(
        monkeypatch,
        {"npc": ProposalRejectedError("Invalid intention"), "peer": ChpmError("Wrong session")},
    )
    with pytest.raises(ChpmError, match="Wrong session"):
        await dispatch(value)
    assert not value.decisions and not value.usage.actor_failures


async def test_all_rejected_proposals_keep_the_existing_global_recovery_boundary(monkeypatch):
    value = turn()
    install(monkeypatch, {actor: ProposalRejectedError("Invalid") for actor in value.names})
    with pytest.raises(ProposalRejectedError):
        await dispatch(value)
    assert not value.decisions and set(value.usage.actor_failures) == {"npc", "peer"}


async def test_cancelled_parallel_work_never_publishes_the_completed_peer(monkeypatch):
    value = turn()
    install(monkeypatch, {"npc": asyncio.CancelledError()})
    with pytest.raises(asyncio.CancelledError):
        await dispatch(value)
    assert not value.decisions and not value.usage.actor_failures


async def test_deferred_actor_does_not_consume_the_next_actors_repair_reserve(monkeypatch):
    value = turn()
    value.initial.settings.npc_concurrency = 1
    value.initial.settings.max_calls_per_turn = 7
    value.usage.calls = 2  # Shared perception and the first completed, truncated proposal.
    calls = []

    async def request(_host, settings, usage, _instruction, _payload, _schema, phase, **_kwargs):
        inference.reserve(settings, usage, 1)
        calls.append(phase)
        return Response(value="valid" if phase == "proposal_repair" else "bad")

    def accept(reply):
        if reply.value == "bad":
            raise ChpmError("Invalid candidate")
        return reply

    host = SimpleNamespace(_chpm_turn=value)

    async def prepare(_host, current, actor, _observed):
        if actor.id == "npc":
            raise ProposalRejectedError("Truncated proposal")
        await proposal_attempt.request(
            host, current.initial.settings, current.usage, "Policy", {}, Response, {}, accept
        )
        current.decisions[actor.id] = decision().model_copy(update={"actor_id": actor.id})

    monkeypatch.setattr(inference, "request", request)
    await parallel.prepare(
        host, value, [SimpleNamespace(id="npc"), SimpleNamespace(id="peer")], observation(), prepare
    )
    assert calls == ["proposal", "proposal_repair"]
    assert value.usage.calls == 4 and value.usage.proposal_repairs == 1
    assert set(value.decisions) == {"peer"}
