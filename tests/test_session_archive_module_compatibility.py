"""Archive compatibility across ASGI cancellation, deployment and legacy consumers."""

import asyncio
import tempfile
import threading
from typing import BinaryIO

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from alembic import command
from backend.api.routes.adventures.session_transfer import SessionArchiveResponse
from backend.core.config import settings
from backend.main import app
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.utils.async_files import run_file_operation
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


class _SlowArchive:
    def __init__(self, source: BinaryIO) -> None:
        self.source = source
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.close_started = threading.Event()
        self.closed_before_read_finished = False

    def read(self, size: int) -> bytes:
        self.entered.set()
        try:
            if not self.release.wait(5):
                raise RuntimeError("The test did not release its archive reader.")
            return self.source.read(size)
        finally:
            self.finished.set()

    def close(self) -> None:
        self.closed_before_read_finished = not self.finished.is_set()
        self.close_started.set()
        self.source.close()


async def test_asgi23_disconnect_waits_for_archive_worker_before_closing_its_file():
    with tempfile.TemporaryFile(mode="w+b") as source:
        source.write(b"portable save")
        source.seek(0)
        archive = _SlowArchive(source)
        response = SessionArchiveResponse(archive, 13, "session")
        disconnected = asyncio.Event()

        async def receive():
            assert await asyncio.to_thread(archive.entered.wait, 3)
            disconnected.set()
            return {"type": "http.disconnect"}

        async def send(_message):
            return None

        task = asyncio.create_task(
            response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send)
        )
        try:
            await asyncio.wait_for(disconnected.wait(), 3)
            await asyncio.to_thread(archive.close_started.wait, 0.2)
        finally:
            archive.release.set()
            await asyncio.wait_for(task, 3)
        assert not archive.closed_before_read_finished
        assert source.closed


@pytest.mark.parametrize("worker_error", [False, True])
async def test_repeated_explicit_cancellation_keeps_file_alive_until_worker_finishes(worker_error):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    with tempfile.TemporaryFile(mode="w+b") as source:
        source.write(b"portable save")
        source.seek(0)

        def operation():
            entered.set()
            try:
                if not release.wait(5):
                    raise RuntimeError("The test did not release its file worker.")
                if worker_error:
                    raise ValueError("Worker failure must not replace caller cancellation.")
                return source.read()
            finally:
                finished.set()

        async def transfer():
            try:
                return await run_file_operation(operation)
            finally:
                source.close()

        task = asyncio.create_task(transfer())
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel("first cancellation")
            await asyncio.sleep(0)
            task.cancel("second cancellation")
            done, _pending = await asyncio.wait({task}, timeout=0.05)
            assert not done
            assert not source.closed
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError) as cancelled:
                await task
            assert await asyncio.to_thread(finished.wait, 3)
        assert source.closed
        assert str(cancelled.value) == "first cancellation"


async def test_immediate_file_result_and_error_are_preserved():
    assert await run_file_operation(lambda: b"complete") == b"complete"

    def operation():
        raise ValueError("Immediate worker error")

    with pytest.raises(ValueError, match="Immediate worker error"):
        await run_file_operation(operation)


@pytest.mark.parametrize("role", ["user", "admin"])
async def test_ads_file_routes_keep_owner_bound_authentication(auth_client, portrait_world, role):
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User).where(User.username == "test_user"))
        owner.role = role
        owner_id = owner.id
        await db.commit()

    exported = await auth_client.get("/api/adventures/sessions/portrait-session/export")
    assert exported.status_code == 200
    foreign = await auth_client.get("/api/adventures/sessions/other-session/export")
    assert foreign.status_code == 404
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("save.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    async with TestSessionLocal() as db:
        assert (await db.get(GameSession, imported.json()["game_id"])).user_id == owner_id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anonymous:
        assert (
            await anonymous.get("/api/adventures/sessions/portrait-session/export")
        ).status_code == 401
        assert (
            await anonymous.post(
                "/api/adventures/sessions/import",
                files={"file": ("save.ads", exported.content, "application/zip")},
            )
        ).status_code == 401


@pytest.mark.parametrize("existing_main_schema", [False, True])
def test_notebook_migration_registers_on_fresh_and_existing_main_databases(
    tmp_path, monkeypatch, existing_main_schema
):
    database = tmp_path / "compatibility.sqlite"
    url = "sqlite:///" + str(database)
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    engine = create_engine(url)
    try:
        if existing_main_schema:
            command.upgrade(config, "ab17c8d9e602")
            with Session(engine) as session:
                session.add(
                    User(
                        id="archive-compat-owner",
                        username="archive-compat-owner",
                        hashed_password="unused-test-fixture",
                        role="user",
                        bio="Retained profile",
                    )
                )
                session.commit()
            assert "npc_notebooks" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as connection:
            schema = inspect(connection)
            assert "npc_notebooks" in schema.get_table_names()
            assert any(
                set(constraint["column_names"]) == {"session_id", "npc_id"}
                for constraint in schema.get_unique_constraints("npc_notebooks")
            )
            assert any(
                "16000000" in constraint["sqltext"]
                for constraint in schema.get_check_constraints("npc_notebooks")
            )
            if existing_main_schema:
                assert connection.scalar(text("SELECT bio FROM users")) == "Retained profile"
    finally:
        engine.dispose()
