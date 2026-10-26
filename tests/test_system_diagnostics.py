"""Diagnostic logs contain operational metadata, never player content or credentials."""

import json
import logging
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.core import system_diagnostics
from backend.core.system_diagnostics import DiagnosticService, service
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
SECRET = "PRIVATE_DIALOGUE_AND_API_KEY_DO_NOT_LOG"


@pytest.fixture(autouse=True)
def isolated_diagnostics(tmp_path, monkeypatch):
    service.close()
    monkeypatch.setattr(service, "directory", tmp_path / "log")
    service.write_failed = False
    yield
    service.close()


def records():
    return [
        json.loads(line)
        for line in (service.directory / "system-debug.jsonl").read_text().splitlines()
    ]


def test_disabled_creates_no_log_and_enabled_drops_all_text_and_arguments():
    original_level = logging.getLogger().level
    session_id = str(uuid4())
    service.emit("llm.started", prompt=SECRET)
    assert not service.directory.exists()
    service.set_enabled(True)
    with service.context(session_id=session_id, prompt=SECRET):
        service.emit(
            "llm.completed",
            duration_ms=12.5,
            provider="openai",
            response=SECRET,
            metadata={"prompt": SECRET},
        )
        try:
            raise ValueError(SECRET)
        except ValueError:
            logging.getLogger("backend.example").exception("Player said %s", SECRET)
    text = (service.directory / "system-debug.jsonl").read_text()
    assert SECRET not in text
    assert session_id in text
    assert "ValueError" in text
    assert "test_disabled_creates_no_log" in text
    assert logging.getLogger().level == original_level
    assert any(row.get("duration_ms") == 12.5 for row in records())
    assert all(
        "error" not in row or not row["error"] or "message" not in row["error"] for row in records()
    )


def test_switch_survives_restart_and_off_stops_new_writes():
    service.set_enabled(True)
    service.close()
    restarted = DiagnosticService(service.directory)
    restarted.initialize()
    assert restarted.enabled
    restarted.set_enabled(False)
    before = (service.directory / "system-debug.jsonl").read_bytes()
    restarted.emit("llm.started")
    assert (service.directory / "system-debug.jsonl").read_bytes() == before
    restarted.initialize()
    assert not restarted.enabled


def test_rotation_is_bounded_and_unknown_fields_are_ignored(monkeypatch):
    monkeypatch.setattr(system_diagnostics, "MAX_BYTES", 450)
    service.set_enabled(True)
    for _ in range(40):
        service.emit("llm.started", model=SECRET, api_key=SECRET, duration_ms=10**1000)
    files = list(service.directory.glob("system-debug.jsonl*"))
    assert 1 < len(files) <= 5
    for file in files:
        assert SECRET not in file.read_text()
        for line in file.read_text().splitlines():
            json.loads(line)


def test_storage_failure_does_not_interrupt_gameplay(monkeypatch):
    service.set_enabled(True)

    def unavailable(_record):
        raise OSError(SECRET)

    monkeypatch.setattr(service._writer, "emit", unavailable)
    service.emit("llm.completed", duration_ms=100)
    assert service.status()["write_error"] == "Diagnostic storage is unavailable."
    assert SECRET not in json.dumps(service.status())


async def test_admin_can_toggle_and_invalid_payload_is_rejected(auth_client):
    assert (await auth_client.get("/api/system-diagnostics")).json()["enabled"] is False
    response = await auth_client.put("/api/system-diagnostics", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["log_directory"] == "log"
    assert service.enabled
    assert (
        await auth_client.put("/api/system-diagnostics", json={"enabled": "false"})
    ).status_code == 422
    assert (
        await auth_client.put("/api/system-diagnostics", json={"enabled": False})
    ).status_code == 200
    assert not service.enabled


async def test_non_admin_cannot_read_or_change_diagnostics(auth_client):
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User))
        user.role = "user"
        await db.commit()
    assert (await auth_client.get("/api/system-diagnostics")).status_code == 403
    assert (
        await auth_client.put("/api/system-diagnostics", json={"enabled": True})
    ).status_code == 403


async def test_http_log_excludes_paths_queries_headers_and_bodies(auth_client):
    service.set_enabled(True)
    await auth_client.post(
        f"/api/not-found/{SECRET}?secret={SECRET}",
        json={"content": SECRET},
        headers={"X-Secret": SECRET},
    )
    text = (service.directory / "system-debug.jsonl").read_text()
    assert SECRET not in text
    response = [row for row in records() if row["event"] == "http.completed"][-1]
    assert response["route"] == "<unmatched>"
    assert response["status_code"] in (404, 405)
    assert response["duration_ms"] >= 0
    assert response["request_id"]


async def test_player_snapshot_flag_tracks_system_switch(auth_client, portrait_world):
    path = "/api/adventures/portrait-session/chat"
    assert (await auth_client.get(path)).json()["system_debug_enabled"] is False
    service.set_enabled(True)
    assert (await auth_client.get(path)).json()["system_debug_enabled"] is True
    service.set_enabled(False)
    assert (await auth_client.get(path)).json()["system_debug_enabled"] is False
