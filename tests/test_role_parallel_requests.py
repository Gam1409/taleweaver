"""Role permissions bound shared admission without weakening completion ownership."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.core.inference import admission, transport
from backend.core.inference.registry import InferenceUncertainError, Registry, endpoint_key
from backend.core.llm_parallel import ParallelPolicy, ParallelSettings, resolve
from tests.test_custom_openai import local_policy
from tests.test_custom_openai_roles import preferences

__all__ = ["local_policy"]
KEY = endpoint_key("http://localhost:8080/v1")


@pytest.fixture
def reservations(tmp_path, monkeypatch):
    owner = Registry(tmp_path / "reservations.json")
    monkeypatch.setattr(admission, "_registry", owner)
    return owner


def test_legacy_and_role_local_permissions_do_not_inherit_from_donor_models():
    assert resolve({}, "small") is None
    settings = {"parallel_requests": {"roles": {"complex": {"enabled": True, "max_concurrent": 3}}}}
    assert resolve(settings, "complex").capacity == 3
    assert resolve(settings, "small").capacity == 1
    assert resolve(settings, None).capacity == 1
    assert ParallelPolicy(enabled=False, max_concurrent=4).capacity == 1


@pytest.mark.parametrize("value", [0, 1, 5, 2.5, True, "2"])
def test_invalid_limits_are_rejected(value):
    with pytest.raises(ValidationError):
        ParallelPolicy(max_concurrent=value)


def test_capacity_mixed_roles_exclusivity_and_waiter_fairness(reservations):
    first = reservations.enqueue(KEY, capacity=3)
    second = reservations.enqueue(KEY, capacity=2)
    third = reservations.enqueue(KEY, capacity=3)
    assert reservations.try_acquire(first)
    assert reservations.try_acquire(second)
    assert not reservations.try_acquire(third)
    reservations.finish(second, certain=True)
    assert reservations.try_acquire(third)
    exclusive = reservations.enqueue(KEY)
    later = reservations.enqueue(KEY, capacity=4)
    assert not reservations.try_acquire(exclusive)
    assert not reservations.try_acquire(later)
    reservations.finish(first, certain=True)
    reservations.finish(third, certain=True)
    assert reservations.try_acquire(exclusive)
    assert not reservations.try_acquire(later)
    reservations.finish(exclusive, certain=True)
    assert reservations.try_acquire(later)
    reservations.finish(later, certain=True)
    assert reservations.status() == []


def test_uncertain_parallel_slot_fences_all_roles_and_survives_restart(reservations):
    first = reservations.enqueue(KEY, capacity=2)
    second = reservations.enqueue(KEY, capacity=2)
    assert reservations.try_acquire(first) and reservations.try_acquire(second)
    reservations.finish(first, certain=False)
    for owner in (reservations, Registry(reservations.path)):
        waiter = owner.enqueue(KEY, capacity=4)
        with pytest.raises(InferenceUncertainError):
            owner.try_acquire(waiter)
        owner.forget(waiter)
    reservations.finish(second, certain=True)
    assert [row["token"] for row in reservations.status()] == [first.token]
    reservations.acknowledge_stopped(first.record_key, first.token)
    newer = reservations.enqueue(KEY, capacity=2)
    assert reservations.try_acquire(newer)
    reservations.finish(first, certain=True)
    assert [row["token"] for row in reservations.status()] == [newer.token]
    reservations.finish(newer, certain=True)


async def test_opt_in_guards_cloud_and_local_even_without_legacy_flag(reservations, monkeypatch):
    from backend.core.config import settings

    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", False)
    active, peak = 0, 0
    two_entered, release = asyncio.Event(), asyncio.Event()

    @transport.guarded_async
    async def call(router, kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            two_entered.set()
        await release.wait()
        active -= 1
        return "ok"

    for provider, url in (("custom_openai", "http://localhost:8080/v1"), ("deepseek", None)):
        client = SimpleNamespace(
            provider=provider,
            api_base=url,
            request_timeout=2,
            parallel_policy=ParallelPolicy(enabled=True),
        )
        tasks = [asyncio.create_task(call(client, {})) for _ in range(3)]
        try:
            await asyncio.wait_for(two_entered.wait(), 1)
            await asyncio.sleep(0.04)
            assert active == peak == 2
            assert len(reservations.status()) == 2
        finally:
            release.set()
            await asyncio.gather(*tasks)
        assert reservations.status() == []
        peak = 0
        two_entered.clear()
        release.clear()


async def test_settings_save_reload_and_invalid_update_are_atomic(auth_client, local_policy):
    old = (await auth_client.get("/api/settings")).json()["llm_settings"]
    policy = ParallelSettings(roles={"small": ParallelPolicy(enabled=True)}).model_dump()
    response = await auth_client.post(
        "/api/settings/llm", json={**old, **preferences(), "parallel_requests": policy}
    )
    assert response.status_code == 200, response.text
    saved = (await auth_client.get("/api/settings")).json()["llm_settings"]
    assert saved["parallel_requests"] == policy
    invalid = deepcopy(saved)
    invalid["parallel_requests"]["roles"]["small"]["max_concurrent"] = 9
    assert (await auth_client.post("/api/settings/llm", json=invalid)).status_code == 422
    assert (await auth_client.get("/api/settings")).json()["llm_settings"] == saved
    legacy_client = {key: value for key, value in saved.items() if key != "parallel_requests"}
    assert (await auth_client.post("/api/settings/llm", json=legacy_client)).status_code == 200
    assert (await auth_client.get("/api/settings")).json()["llm_settings"][
        "parallel_requests"
    ] == policy


async def test_admin_can_recover_only_the_uncertain_parallel_slot(auth_client, reservations):
    ticket = reservations.enqueue(KEY, capacity=2)
    assert reservations.try_acquire(ticket)
    payload = {
        "endpoint_id": ticket.record_key,
        "token": ticket.token,
        "confirmation": "REMOTE_GENERATION_STOPPED",
    }
    path = "/api/inference-queue/acknowledge-stopped"
    assert (await auth_client.post(path, json=payload)).status_code == 409
    reservations.finish(ticket, certain=False)
    assert (await auth_client.post(path, json=payload)).status_code == 200


async def test_real_role_router_keeps_prompts_and_shares_capacity_with_exclusive_role(
    reservations, monkeypatch
):
    from backend.core.llm_router import GameMasterLLM
    from backend.models.user import User

    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            entered.set()
        await release.wait()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], model_dump=lambda: {}
        )

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", complete)
    user = User(
        llm_settings={
            "small_model_provider": "ollama",
            "small_model": "local",
            "complex_model_provider": "ollama",
            "complex_model": "local",
            "parallel_requests": {"roles": {"small": {"enabled": True}}},
        }
    )
    small = GameMasterLLM.for_role(user, "small")
    complex_role = GameMasterLLM.for_role(user, "complex")
    tasks = [
        asyncio.create_task(small.aexecute_simple_task("system", str(i), small.model))
        for i in range(2)
    ]
    try:
        await asyncio.wait_for(entered.wait(), 1)
        exclusive = asyncio.create_task(
            complex_role.aexecute_simple_task("narrate", "scene", complex_role.model)
        )
        tasks.append(exclusive)
        await asyncio.sleep(0.04)
        assert len(calls) == 2 and not exclusive.done()
    finally:
        release.set()
        assert await asyncio.gather(*tasks) == ["ok"] * len(tasks)
    assert [call["messages"][0]["content"] for call in calls] == ["system", "system", "narrate"]
    assert [call["messages"][1]["content"] for call in calls] == ["0", "1", "scene"]
    assert all(call["num_retries"] == 0 for call in calls)
    assert reservations.status() == []


def test_explicit_policy_does_not_add_the_legacy_living_world_lane(reservations):
    from backend.core.inference.registry import concurrent_call

    first = reservations.enqueue(KEY, capacity=2)
    token = concurrent_call.set(True)
    try:
        second = reservations.enqueue(KEY, capacity=2)
        third = reservations.enqueue(KEY, capacity=2)
    finally:
        concurrent_call.reset(token)
    assert reservations.try_acquire(first)
    assert reservations.try_acquire(second)
    assert not reservations.try_acquire(third)
    assert not second.concurrent
    reservations.finish(first, certain=True)
    reservations.finish(second, certain=True)
    reservations.forget(third)


def test_legacy_lane_and_new_capacity_cannot_overlap_during_settings_change(reservations):
    from backend.core.inference.registry import concurrent_call

    token = concurrent_call.set(True)
    try:
        legacy = reservations.enqueue(KEY)
    finally:
        concurrent_call.reset(token)
    assert reservations.try_acquire(legacy)
    configured = reservations.enqueue(KEY, capacity=2)
    assert not reservations.try_acquire(configured)
    reservations.finish(legacy, certain=True)
    assert reservations.try_acquire(configured)
    token = concurrent_call.set(True)
    try:
        other = reservations.enqueue(KEY)
    finally:
        concurrent_call.reset(token)
    assert not reservations.try_acquire(other)
    reservations.finish(configured, certain=True)
    assert reservations.try_acquire(other)
    reservations.finish(other, certain=True)


@pytest.mark.parametrize("role", ["small", "complex", "generator", "compression", "play_agent"])
def test_all_roles_retain_their_own_policy_when_the_model_is_inherited(role):
    from backend.core.llm_router import GameMasterLLM
    from backend.models.user import User

    cfg = {
        "small_model_provider": "ollama",
        "small_model": "local",
        "parallel_requests": {"roles": {role: {"enabled": True, "max_concurrent": 3}}},
    }
    client = GameMasterLLM.for_role(User(llm_settings=cfg), role)
    assert client.parallel_policy.capacity == 3
    assert client.model == "local"


async def test_late_receipt_releases_only_its_parallel_slot(reservations):
    entered = {name: asyncio.Event() for name in ("old", "peer")}
    release = {name: asyncio.Event() for name in entered}

    @transport.guarded_async
    async def call(client, kwargs):
        name = kwargs["id"]
        entered[name].set()
        await release[name].wait()
        return name

    client = SimpleNamespace(
        provider="deepseek",
        api_base=None,
        request_timeout=2,
        parallel_policy=ParallelPolicy(enabled=True),
    )
    old = asyncio.create_task(call(client, {"id": "old"}))
    peer = asyncio.create_task(call(client, {"id": "peer"}))
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered.values())), 1)
        old.cancel()
        with pytest.raises(asyncio.CancelledError):
            await old
        assert len(reservations.status()) == 2
        assert all(row["status"] == "RUNNING" for row in reservations.status())
        release["old"].set()
        async with asyncio.timeout(1):
            while len(reservations.status()) != 1:
                await asyncio.sleep(0.005)
        assert not peer.done()
        assert reservations.status()[0]["status"] == "RUNNING"
    finally:
        for event in release.values():
            event.set()
        await asyncio.gather(old, peer, return_exceptions=True)
    assert await peer == "peer"
    assert reservations.status() == []
