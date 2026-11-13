"""Password changes renew the authorized browser without reviving revoked credentials."""

from types import SimpleNamespace

import httpx
import jwt
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes import account_api, auth_api
from backend.core.auth import create_user_access_token
from backend.core.database import get_db
from backend.models.user import User
from backend.utils import media_access
from backend.utils.static_media import SafeStaticFiles
from tests.conftest import TestSessionLocal
from tests.test_account_security import NEW_PASSWORD, PASSWORD, _create_user

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def media_api(setup_test_db, monkeypatch, tmp_path):
    user = await _create_user("media-fixture")
    async with TestSessionLocal() as db:
        saved = await db.get(User, user.id)
        saved.has_imported_defaults = True
        await db.commit()
    app = FastAPI()
    app.include_router(account_api.router, prefix="/api")
    app.include_router(auth_api.router, prefix="/api")

    async def isolated_db():
        async with TestSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    monkeypatch.setattr(media_access, "AsyncSessionLocal", TestSessionLocal)
    (tmp_path / "probe.png").write_bytes(b"NEUTRAL_PASSIVE_FIXTURE")
    app.mount("/data", SafeStaticFiles(directory=tmp_path))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="https://fixture") as client:
        headers = {"Authorization": "Bearer " + create_user_access_token(user)}
        assert (await client.get("/api/auth/me", headers=headers)).status_code == 200
        assert (await client.get("/data/probe.png")).status_code == 200
        yield SimpleNamespace(client=client, headers=headers, user=user, app=app)


def claims(token):
    return jwt.decode(token, options={"verify_signature": False})


@pytest.mark.parametrize("rename", [False, True])
async def test_credentials_response_renews_current_browser_media(media_api, rename):
    api = media_api
    old_cookie = api.client.cookies.get(media_access.COOKIE)
    payload = {"current_password": PASSWORD, "password": NEW_PASSWORD}
    if rename:
        payload["username"] = "renamed-fixture"
    changed = await api.client.put("/api/users/me/credentials", headers=api.headers, json=payload)
    assert changed.status_code == 200, changed.text
    fresh_cookie = changed.cookies.get(media_access.COOKIE)
    assert fresh_cookie and fresh_cookie != old_cookie
    access_token = changed.json()["access_token"]
    assert claims(fresh_cookie)["ver"] == claims(access_token)["ver"] == 1
    assert claims(fresh_cookie)["sub"] == api.user.id
    assert claims(fresh_cookie)["aud"] == "media"
    attributes = changed.headers["set-cookie"].lower()
    assert "httponly" in attributes and "secure" in attributes
    assert "path=/data" in attributes and "samesite=strict" in attributes
    assert (await api.client.get("/data/probe.png")).status_code == 200
    assert (await api.client.get("/api/users/me/sessions", headers=api.headers)).status_code == 401
    assert (
        await api.client.get(
            "/api/users/me/sessions", headers={"Authorization": "Bearer " + access_token}
        )
    ).status_code == 200
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app), base_url="https://fixture"
    ) as other:
        assert (
            await other.get("/data/probe.png", headers={"Cookie": f"tw_media={old_cookie}"})
        ).status_code == 401


@pytest.mark.parametrize("failure", ["current_password", "commit"])
async def test_rejected_or_uncommitted_change_issues_no_replacement_cookie(
    media_api, monkeypatch, failure
):
    api = media_api
    payload = {"current_password": PASSWORD, "password": NEW_PASSWORD}
    if failure == "current_password":
        payload["current_password"] = "incorrect-fixture"
    else:

        async def fail(_session):
            raise RuntimeError("Synthetic commit failure")

        monkeypatch.setattr(AsyncSession, "commit", fail)
    result = await api.client.put("/api/users/me/credentials", headers=api.headers, json=payload)
    assert result.status_code == (400 if failure == "current_password" else 500)
    assert "set-cookie" not in result.headers
    async with TestSessionLocal() as db:
        saved = await db.get(User, api.user.id)
        assert saved.token_version == 0
    assert (await api.client.get("/data/probe.png")).status_code == 200


async def test_media_cookie_uses_rotation_version_even_if_later_refresh_observes_a_new_one(
    media_api, monkeypatch
):
    api = media_api
    original_refresh = AsyncSession.refresh
    rotated = False

    async def refresh(session, instance, *args, **kwargs):
        nonlocal rotated
        if (
            isinstance(instance, User)
            and instance.id == api.user.id
            and instance.token_version == 1
            and not rotated
        ):
            rotated = True
            async with TestSessionLocal() as other:
                await other.execute(
                    update(User).where(User.id == api.user.id).values(token_version=2)
                )
                await other.commit()
        return await original_refresh(session, instance, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "refresh", refresh)
    result = await api.client.put(
        "/api/users/me/credentials",
        headers=api.headers,
        json={"current_password": PASSWORD, "password": NEW_PASSWORD},
    )
    assert result.status_code == 200, result.text
    assert rotated
    assert (
        claims(result.cookies[media_access.COOKIE])["ver"]
        == claims(result.json()["access_token"])["ver"]
        == 1
    )
    assert (await api.client.get("/data/probe.png")).status_code == 401
