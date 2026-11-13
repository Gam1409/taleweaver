"""Concurrent recovery must consume its proof and rotate credentials atomically."""

import asyncio

import jwt
import pytest
import pytest_asyncio

from backend.core import account_recovery
from tests.account_recovery_support import (
    FIRST_PASSWORD,
    PASSWORD,
    SECOND_PASSWORD,
    USER_ID,
    USERNAME,
    HashGate,
    account_api_fixture,
    fixture_hash,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def recovery_api(tmp_path, monkeypatch):
    async for fixture in account_api_fixture(tmp_path, monkeypatch):
        yield fixture


def _token_version(response) -> int:
    return jwt.decode(response.json()["access_token"], options={"verify_signature": False})["ver"]


async def _overlap(api, monkeypatch, first, second):
    gate = HashGate()
    monkeypatch.setattr(account_recovery, "aget_password_hash", gate.hash)
    tasks = [asyncio.create_task(first), asyncio.create_task(second)]
    await asyncio.wait_for(gate.ready.wait(), 5)
    assert len(api.connections) >= 2
    gate.release.set()
    return await asyncio.gather(*tasks)


@pytest.mark.parametrize("method", ["token", "code"])
async def test_concurrent_reuse_has_one_winner(recovery_api, monkeypatch, method):
    api = recovery_api
    responses = await _overlap(
        api,
        monkeypatch,
        api.reset(method, FIRST_PASSWORD),
        api.reset(method, SECOND_PASSWORD),
    )

    assert sorted(response.status_code for response in responses) == [200, 400]
    winner = next(response for response in responses if response.status_code == 200)
    user = await api.user()
    assert user.token_version == 1
    assert user.hashed_password in {fixture_hash(FIRST_PASSWORD), fixture_hash(SECOND_PASSWORD)}
    assert user.recovery_codes_remaining == (9 if method == "code" else 10)
    assert _token_version(winner) == 1
    assert (await api.probe(winner.json()["access_token"])).status_code == 200
    assert (await api.probe(api.token)).status_code == 401
    assert (await api.reset(method, FIRST_PASSWORD)).status_code == 400


async def test_distinct_concurrent_codes_preserve_remaining_codes_and_versions(
    recovery_api, monkeypatch
):
    api = recovery_api
    responses = await _overlap(
        api,
        monkeypatch,
        api.reset("code", FIRST_PASSWORD),
        api.reset("code", SECOND_PASSWORD, code_index=1),
    )

    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(_token_version(response) for response in responses) == [1, 2]
    assert (await api.user()).token_version == 2
    assert (await api.user()).recovery_codes_remaining == 8
    for response in responses:
        expected = 200 if _token_version(response) == 2 else 401
        assert (await api.probe(response.json()["access_token"])).status_code == expected
    monkeypatch.setattr(account_recovery, "aget_password_hash", _hash_immediately)
    assert (await api.reset("code", FIRST_PASSWORD)).status_code == 400
    assert (await api.reset("code", FIRST_PASSWORD, code_index=1)).status_code == 400
    assert (await api.reset("code", FIRST_PASSWORD, code_index=2)).status_code == 200
    assert (await api.user()).recovery_codes_remaining == 7
    assert (await api.reset("token", FIRST_PASSWORD)).status_code == 400


async def _hash_immediately(password):
    return fixture_hash(password)


async def test_concurrent_admin_password_updates_increment_in_database(recovery_api, monkeypatch):
    api = recovery_api
    responses = await _overlap(
        api,
        monkeypatch,
        api.client.put(
            f"/api/users/{USER_ID}", headers=api.headers, json={"password": FIRST_PASSWORD}
        ),
        api.client.put(
            f"/api/users/{USER_ID}", headers=api.headers, json={"password": SECOND_PASSWORD}
        ),
    )

    assert [response.status_code for response in responses] == [200, 200]
    assert (await api.user()).token_version == 2
    assert (await api.user()).password_reset_token_hash is None
    assert (await api.probe(api.token)).status_code == 401


async def test_concurrent_self_service_changes_require_current_credentials(
    recovery_api, monkeypatch
):
    api = recovery_api
    responses = await _overlap(
        api,
        monkeypatch,
        *(
            api.client.put(
                "/api/users/me/credentials",
                headers=api.headers,
                json={"current_password": PASSWORD, "password": password},
            )
            for password in (FIRST_PASSWORD, SECOND_PASSWORD)
        ),
    )

    assert sorted(response.status_code for response in responses) == [200, 400]
    winner = next(response for response in responses if response.status_code == 200)
    assert _token_version(winner) == 1
    assert (await api.user()).token_version == 1
    assert (await api.probe(winner.json()["access_token"])).status_code == 200
    assert (await api.probe(api.token)).status_code == 401


async def test_password_reset_invalidates_inflight_verified_credential_update(
    recovery_api, monkeypatch
):
    api = recovery_api
    gate = HashGate(expected=1)
    monkeypatch.setattr(account_recovery, "aget_password_hash", gate.hash)
    change = asyncio.create_task(
        api.client.put(
            "/api/users/me/credentials",
            headers=api.headers,
            json={
                "current_password": PASSWORD,
                "username": "renamed_fixture",
                "password": SECOND_PASSWORD,
            },
        )
    )
    await asyncio.wait_for(gate.ready.wait(), 5)
    monkeypatch.setattr(account_recovery, "aget_password_hash", _hash_immediately)
    reset = await api.reset("token", FIRST_PASSWORD)
    gate.release.set()
    changed = await change

    assert reset.status_code == 200
    assert changed.status_code == 400
    user = await api.user()
    assert user.username == USERNAME
    assert user.hashed_password == fixture_hash(FIRST_PASSWORD)
    assert user.token_version == 1
    assert (await api.probe(reset.json()["access_token"])).status_code == 200
