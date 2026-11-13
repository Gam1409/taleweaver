"""Reset-link expiry is evaluated after waiting for SQLite's database writer."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Update

from backend.core import account_recovery
from backend.models.user import User
from tests.account_recovery_support import (
    FIRST_PASSWORD,
    PASSWORD,
    USER_ID,
    account_api_fixture,
    fixture_hash,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def recovery_api(tmp_path, monkeypatch):
    async for fixture in account_api_fixture(tmp_path, monkeypatch):
        yield fixture


async def test_reset_link_expires_while_waiting_for_sqlite_writer(recovery_api, monkeypatch):
    api = recovery_api

    async def immediate_hash(password):
        return fixture_hash(password)

    monkeypatch.setattr(account_recovery, "aget_password_hash", immediate_hash)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    async with api.sessions() as db:
        user = await db.get(User, USER_ID)
        user.password_reset_expires_at = expires_at
        await db.commit()

    reached_update = asyncio.Event()
    original_execute = AsyncSession.execute

    async def observe_update(db, statement, *args, **kwargs):
        if isinstance(statement, Update):
            reached_update.set()
        return await original_execute(db, statement, *args, **kwargs)

    async with api.sessions() as blocker:
        await blocker.execute(update(User).where(User.id == USER_ID).values(bio="fixture lock"))
        monkeypatch.setattr(AsyncSession, "execute", observe_update)
        pending = asyncio.create_task(api.reset("token", FIRST_PASSWORD))
        await asyncio.wait_for(reached_update.wait(), 5)
        delay = (expires_at - datetime.now(timezone.utc)).total_seconds()
        await asyncio.sleep(max(0, delay) + 0.1)
        assert not pending.done()
        assert datetime.now(timezone.utc) > expires_at
        await blocker.commit()
        response = await pending

    assert len(api.connections) >= 2
    assert response.status_code == 400
    user = await api.user()
    assert user.token_version == 0
    assert user.hashed_password == fixture_hash(PASSWORD)
    assert user.password_reset_token_hash is not None
    assert user.password_reset_expires_at == expires_at.replace(tzinfo=None)


@pytest.mark.parametrize("offset,expected", [(-1, 400), (0, 200), (1, 200)])
async def test_reset_link_expiry_preserves_microsecond_boundary(
    recovery_api, monkeypatch, offset, expected
):
    api = recovery_api
    claim_time = datetime(2030, 1, 2, 3, 4, 5, 500000, tzinfo=timezone.utc)

    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return claim_time.astimezone(tz) if tz is not None else claim_time.replace(tzinfo=None)

    async def immediate_hash(password):
        return fixture_hash(password)

    async with api.sessions() as db:
        user = await db.get(User, USER_ID)
        user.password_reset_expires_at = claim_time + timedelta(microseconds=offset)
        await db.commit()
    monkeypatch.setattr(account_recovery, "datetime", FrozenClock)
    monkeypatch.setattr(account_recovery, "aget_password_hash", immediate_hash)

    response = await api.reset("token", FIRST_PASSWORD)

    assert response.status_code == expected
    user = await api.user()
    assert user.token_version == (1 if expected == 200 else 0)
    assert (user.password_reset_token_hash is None) == (expected == 200)
