"""Rotation JWTs follow the principal committed with the password change."""

import asyncio

import jwt
import pytest
import pytest_asyncio

from backend.core import account_recovery
from tests.account_recovery_support import (
    FIRST_PASSWORD,
    PASSWORD,
    USER_ID,
    HashGate,
    account_api_fixture,
    fixture_hash,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def recovery_api(tmp_path, monkeypatch):
    async for fixture in account_api_fixture(tmp_path, monkeypatch):
        yield fixture


async def _rename(api, method, username):
    if method == "admin":
        return await api.client.put(
            f"/api/users/{USER_ID}", headers=api.headers, json={"username": username}
        )
    return await api.client.put(
        "/api/users/me/credentials",
        headers=api.headers,
        json={"current_password": PASSWORD, "username": username},
    )


@pytest.mark.parametrize("method", ["token", "code", "selfservice"])
@pytest.mark.parametrize("rename_method", ["admin", "selfservice"])
async def test_rotation_uses_principal_renamed_while_password_hash_was_pending(
    recovery_api, monkeypatch, method, rename_method
):
    api = recovery_api
    gate = HashGate(expected=1)
    monkeypatch.setattr(account_recovery, "aget_password_hash", gate.hash)
    if method == "selfservice":
        request = api.client.put(
            "/api/users/me/credentials",
            headers=api.headers,
            json={"current_password": PASSWORD, "password": FIRST_PASSWORD},
        )
    else:
        request = api.reset(method, FIRST_PASSWORD)
    pending = asyncio.create_task(request)
    await asyncio.wait_for(gate.ready.wait(), 5)
    renamed = await _rename(api, rename_method, "renamed_fixture")
    assert renamed.status_code == 200
    assert len(api.connections) >= 2
    gate.release.set()
    response = await pending

    assert response.status_code == 200
    user = await api.user()
    assert user.username == "renamed_fixture"
    assert user.hashed_password == fixture_hash(FIRST_PASSWORD)
    assert user.token_version == 1
    token = response.json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["sub"] == user.username
    assert claims["ver"] == user.token_version
    assert (await api.probe(token)).status_code == 200


@pytest.mark.parametrize("rename_method", ["none", "admin", "selfservice"])
async def test_password_rotation_preserves_its_own_requested_rename(
    recovery_api, monkeypatch, rename_method
):
    api = recovery_api
    gate = HashGate(expected=1)
    monkeypatch.setattr(account_recovery, "aget_password_hash", gate.hash)
    pending = asyncio.create_task(
        api.client.put(
            "/api/users/me/credentials",
            headers=api.headers,
            json={
                "current_password": PASSWORD,
                "username": "requested_fixture",
                "password": FIRST_PASSWORD,
            },
        )
    )
    await asyncio.wait_for(gate.ready.wait(), 5)
    if rename_method != "none":
        assert (await _rename(api, rename_method, "external_fixture")).status_code == 200
    gate.release.set()
    response = await pending

    assert response.status_code == 200
    user = await api.user()
    assert user.username == "requested_fixture"
    assert user.hashed_password == fixture_hash(FIRST_PASSWORD)
    token = response.json()["access_token"]
    assert jwt.decode(token, options={"verify_signature": False})["sub"] == user.username
    assert (await api.probe(token)).status_code == 200
