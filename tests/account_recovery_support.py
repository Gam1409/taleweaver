"""Isolated account API fixtures with separate SQLite WAL connections."""

import asyncio
from dataclasses import dataclass, field

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api.routes import account_api, auth_api, users_api
from backend.core import account_recovery
from backend.core.auth import create_user_access_token, get_current_user
from backend.core.database import get_db
from backend.core.login_throttle import recovery_throttle
from backend.models.user import User

PASSWORD = "Original_Fixture493!"
FIRST_PASSWORD = "First_Fixture493!"
SECOND_PASSWORD = "Second_Fixture493!"
USER_ID = "recovery-fixture"
USERNAME = "recovery_fixture"


def fixture_hash(password: str) -> str:
    return f"fixture-hash:{password}"


async def verify_fixture_password(password: str, hashed: str) -> bool:
    return fixture_hash(password) == hashed


@dataclass
class HashGate:
    """Pause both requests after their proof is read, before database writes."""

    expected: int = 2
    arrivals: int = 0
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def hash(self, password: str) -> str:
        self.arrivals += 1
        if self.arrivals == self.expected:
            self.ready.set()
        await asyncio.wait_for(self.release.wait(), 5)
        return fixture_hash(password)


@dataclass
class RecoveryAPI:
    client: AsyncClient
    sessions: async_sessionmaker
    token: str
    reset_token: str
    codes: list[str]
    connections: set[int]

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def user(self) -> User:
        async with self.sessions() as db:
            return await db.get(User, USER_ID)

    async def reset(self, method: str, password: str, code_index: int = 0):
        if method == "token":
            return await self.client.post(
                "/api/auth/reset-password",
                json={"token": self.reset_token, "new_password": password},
            )
        return await self.client.post(
            "/api/auth/recover",
            json={
                "username": USERNAME,
                "recovery_code": self.codes[code_index].lower().replace("-", " "),
                "new_password": password,
            },
        )

    async def probe(self, token: str):
        return await self.client.get("/probe", headers={"Authorization": f"Bearer {token}"})


async def account_api_fixture(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'recovery.db'}")
    connections: set[int] = set()

    @event.listens_for(engine.sync_engine, "connect")
    def configure_connection(connection, _record):
        connections.add(id(connection))
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(User.__table__.create)
        assert (await conn.exec_driver_sql("PRAGMA journal_mode")).scalar_one() == "wal"
    async with sessions() as db:
        user = User(
            id=USER_ID,
            username=USERNAME,
            role="admin",
            hashed_password=fixture_hash(PASSWORD),
            has_imported_defaults=True,
        )
        db.add(user)
        codes = account_recovery.issue_recovery_codes(user)
        reset_token = account_recovery.issue_password_reset_token(user)
        await db.commit()
        token = create_user_access_token(user)

    async def database():
        async with sessions() as db:
            yield db

    async def profile(_db, user):
        return {"id": user.id, "username": user.username, "role": user.role}

    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(users_api.router, prefix="/api")
    app.dependency_overrides[get_db] = database

    @app.get("/probe")
    async def probe(user: User = Depends(get_current_user)):
        return {"id": user.id, "version": user.token_version}

    monkeypatch.setattr(account_api, "build_user_profile_data", profile)
    monkeypatch.setattr(account_api, "averify_password", verify_fixture_password)
    monkeypatch.setattr(auth_api, "averify_password", verify_fixture_password)
    recovery_throttle.clear()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            yield RecoveryAPI(client, sessions, token, reset_token, codes, connections)
    finally:
        recovery_throttle.clear()
        await engine.dispose()
