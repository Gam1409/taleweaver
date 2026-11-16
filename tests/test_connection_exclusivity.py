"""Saved unchecked connection controls fence all roles, including Living World."""

import asyncio

import pytest

from backend.core.config import settings
from backend.core.inference import admission, transport
from backend.core.inference.registry import Registry
from backend.core.llm_router import GameMasterLLM
from backend.engine.living_world.request_slot import decision_slot
from backend.engine.memory_rag import scheduling
from backend.models.user import User


@pytest.mark.parametrize("legacy_enabled", [False, True])
async def test_disabled_connections_serialize_roles_and_legacy_background_lane(
    tmp_path, monkeypatch, legacy_enabled
):
    owner = Registry(tmp_path / "reservations.json")
    monkeypatch.setattr(admission, "_registry", owner)
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", legacy_enabled)
    monkeypatch.setattr(scheduling, "scheduler", scheduling.IdleScheduler(grace_seconds=0))
    roles = ("small", "complex", "generator", "compression", "play_agent")
    user = User(
        llm_settings={
            "small_model_provider": "ollama",
            "small_model": "local",
            "parallel_requests": {
                "roles": {role: {"enabled": False, "max_concurrent": 4} for role in roles}
            },
        }
    )
    active, peak = 0, 0
    first, release = asyncio.Event(), asyncio.Event()
    submitted = []

    @transport.guarded_async
    async def call(client, kwargs):
        nonlocal active, peak
        submitted.append(client.model_category)
        active += 1
        peak = max(peak, active)
        first.set()
        await release.wait()
        active -= 1
        return client.model_category

    async def background():
        async with decision_slot(True):
            return await call(GameMasterLLM.for_role(user, "small"), {})

    tasks = [asyncio.create_task(call(GameMasterLLM.for_role(user, "complex"), {}))]
    try:
        await asyncio.wait_for(first.wait(), 1)
        tasks.extend(
            asyncio.create_task(call(GameMasterLLM.for_role(user, role), {})) for role in roles
        )
        tasks.append(asyncio.create_task(background()))
        await asyncio.sleep(0.05)
        assert submitted == ["complex"] and len(owner.status()) == 1
    finally:
        release.set()
        results = await asyncio.gather(*tasks)
    assert len(results) == 7 and peak == 1
    assert owner.status() == []
