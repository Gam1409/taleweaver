"""Recovery commits, revocation and proof replacement share the same transaction."""

import asyncio
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes import account_api, auth_api
from backend.core import account_recovery
from backend.models.user import User
from tests.account_recovery_support import (
    FIRST_PASSWORD,
    PASSWORD,
    SECOND_PASSWORD,
    USER_ID,
    USERNAME,
    HashGate,
    account_api_fixture,
    fixture_hash,
    verify_fixture_password,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def recovery_api(tmp_path, monkeypatch):
    async for fixture in account_api_fixture(tmp_path, monkeypatch):
        yield fixture


async def _hash_immediately(password):
    return fixture_hash(password)


async def _pause_reset(api, monkeypatch, method):
    gate = HashGate(expected=1)
    monkeypatch.setattr(account_recovery, "aget_password_hash", gate.hash)
    task = asyncio.create_task(api.reset(method, FIRST_PASSWORD))
    await asyncio.wait_for(gate.ready.wait(), 5)
    monkeypatch.setattr(account_recovery, "aget_password_hash", _hash_immediately)
    return gate, task


@pytest.mark.parametrize("pending_method", ["token", "code"])
async def test_overlapping_reset_proofs_obey_commit_order(
    recovery_api, monkeypatch, pending_method
):
    api = recovery_api
    gate, pending = await _pause_reset(api, monkeypatch, pending_method)
    other_method = "code" if pending_method == "token" else "token"
    other = await api.reset(other_method, SECOND_PASSWORD)
    gate.release.set()
    response = await pending

    assert other.status_code == 200
    assert response.status_code == (400 if pending_method == "token" else 200)
    user = await api.user()
    assert user.token_version == (1 if pending_method == "token" else 2)
    assert user.recovery_codes_remaining == 9
    assert user.password_reset_token_hash is None
    expected = 200 if pending_method == "token" else 401
    assert (await api.probe(other.json()["access_token"])).status_code == expected
    if pending_method == "code":
        version = jwt.decode(response.json()["access_token"], options={"verify_signature": False})
        assert version["ver"] == 2
        assert (await api.probe(response.json()["access_token"])).status_code == 200


async def test_replacing_reset_link_rejects_inflight_previous_link(recovery_api, monkeypatch):
    api = recovery_api
    gate, pending = await _pause_reset(api, monkeypatch, "token")
    replacement = await api.client.post(
        f"/api/users/{USER_ID}/password-reset-link", headers=api.headers
    )
    gate.release.set()
    response = await pending

    assert replacement.status_code == 200
    assert response.status_code == 400
    assert (await api.user()).token_version == 0
    used = await api.client.post(
        "/api/auth/reset-password",
        json={"token": replacement.json()["token"], "new_password": SECOND_PASSWORD},
    )
    assert used.status_code == 200
    assert (await api.user()).token_version == 1


async def test_replacing_codes_rejects_inflight_previous_code(recovery_api, monkeypatch):
    api = recovery_api
    gate, pending = await _pause_reset(api, monkeypatch, "code")
    replacement = await api.client.post(
        "/api/users/me/recovery-codes",
        headers=api.headers,
        json={"current_password": PASSWORD},
    )
    gate.release.set()
    response = await pending

    assert replacement.status_code == 200
    assert response.status_code == 400
    user = await api.user()
    assert user.token_version == 0
    assert user.recovery_codes_remaining == 10
    used = await api.client.post(
        "/api/auth/recover",
        json={
            "username": USERNAME,
            "recovery_code": replacement.json()["codes"][0],
            "new_password": SECOND_PASSWORD,
        },
    )
    assert used.status_code == 200
    assert (await api.user()).recovery_codes_remaining == 9


async def test_reset_link_expiring_during_hash_is_rejected(recovery_api, monkeypatch):
    api = recovery_api
    gate, pending = await _pause_reset(api, monkeypatch, "token")
    async with api.sessions() as db:
        user = await db.get(User, USER_ID)
        user.password_reset_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    gate.release.set()

    assert (await pending).status_code == 400
    assert (await api.user()).token_version == 0
    assert (await api.user()).hashed_password == fixture_hash(PASSWORD)


@pytest.mark.parametrize("action", ["codes", "username"])
async def test_sensitive_update_rejects_credentials_revoked_during_verification(
    recovery_api, monkeypatch, action
):
    api = recovery_api
    gate = HashGate(expected=1)

    async def delayed_verify(password, hashed):
        await gate.hash(password)
        return await verify_fixture_password(password, hashed)

    monkeypatch.setattr(account_api, "averify_password", delayed_verify)
    monkeypatch.setattr(account_recovery, "aget_password_hash", _hash_immediately)
    if action == "codes":
        request = api.client.post(
            "/api/users/me/recovery-codes",
            headers=api.headers,
            json={"current_password": PASSWORD},
        )
    else:
        request = api.client.put(
            "/api/users/me/credentials",
            headers=api.headers,
            json={"current_password": PASSWORD, "username": "renamed_fixture"},
        )
    pending = asyncio.create_task(request)
    await asyncio.wait_for(gate.ready.wait(), 5)
    reset = await api.reset("token", FIRST_PASSWORD)
    gate.release.set()
    response = await pending

    assert reset.status_code == 200
    assert response.status_code == 400
    assert (await api.user()).username == USERNAME
    assert (await api.user()).recovery_codes_remaining == 10
    assert (await api.reset("code", SECOND_PASSWORD)).status_code == 200


@pytest.mark.parametrize("method", ["token", "code"])
async def test_failed_commit_rolls_back_proof_password_and_revocation(
    recovery_api, monkeypatch, method
):
    api = recovery_api
    monkeypatch.setattr(account_recovery, "aget_password_hash", _hash_immediately)
    original_commit = AsyncSession.commit
    original_issue = auth_api.create_user_access_token
    issued = []
    fail_next = True

    async def fail_commit_once(db):
        nonlocal fail_next
        if fail_next:
            fail_next = False
            raise RuntimeError("Synthetic commit failure")
        await original_commit(db)

    def record_issue(user):
        issued.append(user.token_version)
        return original_issue(user)

    monkeypatch.setattr(AsyncSession, "commit", fail_commit_once)
    monkeypatch.setattr(auth_api, "create_user_access_token", record_issue)
    failed = await api.reset(method, FIRST_PASSWORD)

    assert failed.status_code == 500
    assert issued == []
    user = await api.user()
    assert user.token_version == 0
    assert user.hashed_password == fixture_hash(PASSWORD)
    assert user.recovery_codes_remaining == 10
    assert user.password_reset_token_hash is not None
    assert (await api.probe(api.token)).status_code == 200
    assert (await api.reset(method, SECOND_PASSWORD)).status_code == 200
    assert issued == [1]


async def test_replacement_jwt_retains_its_own_committed_password_version(
    recovery_api, monkeypatch
):
    api = recovery_api
    monkeypatch.setattr(account_recovery, "aget_password_hash", _hash_immediately)
    original_refresh = AsyncSession.refresh
    rotate_before_refresh = True

    async def refresh_after_another_password_change(db, user, *args, **kwargs):
        nonlocal rotate_before_refresh
        if rotate_before_refresh:
            rotate_before_refresh = False
            async with api.sessions() as other_db:
                other_user = await other_db.get(User, USER_ID)
                other_user.hashed_password = fixture_hash(SECOND_PASSWORD)
                other_user.token_version += 1
                await other_db.commit()
        return await original_refresh(db, user, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "refresh", refresh_after_another_password_change)
    changed = await api.client.put(
        "/api/users/me/credentials",
        headers=api.headers,
        json={"current_password": PASSWORD, "password": FIRST_PASSWORD},
    )

    assert changed.status_code == 200
    token = changed.json()["access_token"]
    assert jwt.decode(token, options={"verify_signature": False})["ver"] == 1
    assert (await api.user()).token_version == 2
    assert (await api.probe(token)).status_code == 401
