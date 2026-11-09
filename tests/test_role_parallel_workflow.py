"""Connection capacity gates cognition, never parallel host state application."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.engine.chpm import actor_preparation, parallel
from backend.engine.chpm.schema import KernelState, Settings
from tests.test_chpm_kernel import decision, observation


@pytest.mark.parametrize(
    "enabled,role_limit,session_limit,expected",
    [(False, 4, 4, 1), (True, 2, 4, 2), (True, 4, 2, 2), (True, 4, 1, 1)],
)
async def test_role_and_session_caps_preserve_preparation_and_atomic_merge(
    monkeypatch, enabled, role_limit, session_limit, expected
):
    actors = [SimpleNamespace(id=str(i)) for i in range(4)]
    turn = SimpleNamespace(
        initial=KernelState(settings=Settings(npc_concurrency=session_limit)),
        decisions={},
        minds={},
    )
    host = SimpleNamespace(
        user=SimpleNamespace(
            llm_settings={
                "parallel_requests": {
                    "roles": {"complex": {"enabled": enabled, "max_concurrent": role_limit}}
                }
            }
        )
    )
    prepared, active, peak = [], 0, 0

    async def prepare(manager, turn, actor, observed):
        assert active == 0
        prepared.append(actor.id)
        return actor_preparation.PreparedActor(actor.id, observed, {}, None, None)

    async def run(manager, turn, job):
        nonlocal active, peak
        if expected > 1:
            assert prepared == [actor.id for actor in actors]
            assert turn.decisions == {}
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return decision(), None

    async def sequential(manager, turn, actor, observed):
        job = await prepare(manager, turn, actor, observed)
        actor_preparation.apply(turn, actor.id, await run(manager, turn, job))

    monkeypatch.setattr(actor_preparation, "prepare", prepare)
    monkeypatch.setattr(actor_preparation, "run", run)
    await parallel.prepare(host, turn, list(reversed(actors)), observation(), sequential)
    assert peak == expected
    assert list(turn.decisions) == [actor.id for actor in actors]
