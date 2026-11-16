"""Portable saves use bounded file transfers at the real upload/download boundary."""

import asyncio
import re
import struct
import tempfile
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, UploadFile
from starlette.requests import ClientDisconnect

from backend.api.routes.adventures import session_transfer
from backend.engine import archive_safety
from backend.engine.chpm.notebook_archive import NotebookArchive
from backend.engine.export_archives import SessionArchiveLimitError, pack_export_ads_to
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


@pytest.fixture
def session_archive_file():
    with tempfile.TemporaryFile(mode="w+b") as archive:
        yield archive


async def test_actual_routes_use_file_apis_instead_of_archive_bytes(
    auth_client, portrait_world, monkeypatch
):
    async def forbid_bytes(*args, **kwargs):
        raise AssertionError("The route must use a file-backed archive.")

    monkeypatch.setattr(SessionExporter, "export_ads", forbid_bytes)
    monkeypatch.setattr(SessionImporter, "import_ads", forbid_bytes)
    exported = await auth_client.get("/api/adventures/sessions/portrait-session/export")
    assert exported.status_code == 200, exported.text
    assert int(exported.headers["content-length"]) == len(exported.content)
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("save.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text


@pytest.mark.parametrize("cancelled", [False, True])
async def test_spooled_upload_is_passed_directly_and_closed(
    monkeypatch, cancelled, session_archive_file
):
    archive = session_archive_file
    archive.write(b"archive bytes")
    upload = UploadFile(file=archive, filename="save.ads")
    captured = []

    async def forbid_read(*args, **kwargs):
        raise AssertionError("UploadFile.read must not load the complete archive.")

    async def import_file(db, source, owner_id):
        captured.append((source, source.tell(), owner_id))
        if cancelled:
            raise asyncio.CancelledError()
        return "restored-session"

    monkeypatch.setattr(upload, "read", forbid_read)
    monkeypatch.setattr(SessionImporter, "import_ads_from", import_file)
    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await session_transfer.import_uploaded_archive(None, upload, "owner")
    else:
        assert (
            await session_transfer.import_uploaded_archive(None, upload, "owner")
            == "restored-session"
        )
    assert captured == [(archive, 0, "owner")]
    assert archive.closed


@pytest.mark.parametrize("declared_size", [None, 65])
async def test_oversized_spooled_upload_is_rejected_before_import(
    monkeypatch, declared_size, session_archive_file
):
    monkeypatch.setattr(archive_safety, "MAX_UPLOAD_BYTES", 64)
    archive = session_archive_file
    archive.truncate(65)
    upload = UploadFile(file=archive, size=declared_size, filename="save.ads")

    async def unexpected_import(*args, **kwargs):
        raise AssertionError("Oversized uploads must be rejected before parsing ZIP data.")

    monkeypatch.setattr(SessionImporter, "import_ads_from", unexpected_import)
    with pytest.raises(HTTPException) as rejected:
        await session_transfer.import_uploaded_archive(None, upload, "owner")
    assert rejected.value.status_code == 413
    assert archive.closed


def test_file_upload_measurement_accepts_the_exact_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_safety, "MAX_UPLOAD_BYTES", 64)
    with (tmp_path / "upload.ads").open("w+b") as archive:
        archive.truncate(64)
        assert archive_safety.rewind_archive(archive) == 64
        assert archive.tell() == 0
        archive.truncate(65)
        with pytest.raises(ValueError, match="upload budget"):
            archive_safety.rewind_archive(archive)


@pytest.mark.parametrize(
    ("entries", "directory_size", "reason"),
    [(1001, 0, "too many entries"), (1, 2 * 1024**3, "metadata budget")],
)
def test_directory_is_bounded_before_zipfile_reads_it(tmp_path, entries, directory_size, reason):
    with (tmp_path / "directory.ads").open("w+b") as archive:
        archive.write(
            struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, entries, entries, directory_size, 0, 0)
        )
        with pytest.raises(ValueError, match=reason):
            archive_safety.validate_archive_stream(archive)


async def test_cancelled_file_import_rolls_back_without_closing_callers_stream(
    monkeypatch, session_archive_file
):
    with zipfile.ZipFile(session_archive_file, "w") as archive:
        archive.writestr("session.json", "{}")
    db = SimpleNamespace(rollback=AsyncMock())

    def cancel_manifest(*_arguments):
        raise asyncio.CancelledError()

    monkeypatch.setattr("backend.engine.session_importer._read_session_manifest", cancel_manifest)
    with pytest.raises(asyncio.CancelledError):
        await SessionImporter.import_ads_from(db, session_archive_file, "owner")
    db.rollback.assert_awaited_once()
    assert not session_archive_file.closed


@pytest.mark.parametrize("failure", ["missing_core", "restore_paths"])
async def test_import_closes_detached_notebook_spool_before_semantic_import(
    monkeypatch, session_archive_file, failure
):
    with zipfile.ZipFile(session_archive_file, "w") as archive:
        archive.writestr("session.json", "{}")
    db = SimpleNamespace(rollback=AsyncMock())
    with tempfile.TemporaryFile(mode="w+b") as notebook_file:
        corpus = NotebookArchive(notebook_file, [], [], 0)
        monkeypatch.setattr("backend.engine.session_importer.read_notebooks", lambda *_args: corpus)

        def fail_paths(*_arguments):
            raise ValueError("Manifest paths are invalid.")

        if failure == "restore_paths":
            monkeypatch.setattr(
                "backend.engine.session_importer._restore_manifest_paths", fail_paths
            )
        assert await SessionImporter.import_ads_from(db, session_archive_file, "owner") is None
        assert notebook_file.closed
    assert not session_archive_file.closed


async def test_cancelled_manifest_worker_still_registers_and_closes_notebook_spool(
    monkeypatch, session_archive_file
):
    with zipfile.ZipFile(session_archive_file, "w") as archive:
        archive.writestr("session.json", "{}")
    db = SimpleNamespace(rollback=AsyncMock())
    entered, release = threading.Event(), threading.Event()
    with tempfile.TemporaryFile(mode="w+b") as notebook_file:
        corpus = NotebookArchive(notebook_file, [], [], 0)

        def read_notebooks(*_arguments):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Cancelled manifest worker was not released.")
            return corpus

        monkeypatch.setattr("backend.engine.session_importer.read_notebooks", read_notebooks)
        task = asyncio.create_task(
            SessionImporter.import_ads_from(db, session_archive_file, "owner")
        )
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert notebook_file.closed
    db.rollback.assert_awaited_once()
    assert not session_archive_file.closed


@pytest.mark.parametrize("disconnect", [False, True])
async def test_download_chunks_and_closes_file_even_on_disconnect(disconnect, session_archive_file):
    archive = session_archive_file
    payload = b"x" * (session_transfer.TRANSFER_CHUNK_BYTES * 3 + 7)
    archive.write(payload)
    archive.seek(0)
    response = session_transfer.SessionArchiveResponse(archive, len(payload), "session")
    chunks = []

    async def send(message):
        if message["type"] != "http.response.body":
            return
        chunks.append(message.get("body", b""))
        if disconnect:
            raise OSError("Client disconnected")

    async def receive():
        return {"type": "http.disconnect"}

    scope = {"type": "http", "asgi": {"spec_version": "2.4"}}
    if disconnect:
        with pytest.raises(ClientDisconnect):
            await response(scope, receive, send)
    else:
        await response(scope, receive, send)
        assert b"".join(chunks) == payload
    assert all(len(chunk) <= session_transfer.TRANSFER_CHUNK_BYTES for chunk in chunks)
    assert archive.closed


@pytest.mark.parametrize("cancelled", [False, True])
async def test_export_closes_temporary_archive_before_returning_a_failure(
    monkeypatch, cancelled, session_archive_file
):
    archive = session_archive_file
    monkeypatch.setattr(session_transfer.tempfile, "TemporaryFile", lambda **kwargs: archive)

    async def fail_export(*args, **kwargs):
        if cancelled:
            raise asyncio.CancelledError()
        raise SessionArchiveLimitError("Too large")

    monkeypatch.setattr(SessionExporter, "export_ads_to", fail_export)
    with pytest.raises(asyncio.CancelledError if cancelled else SessionArchiveLimitError):
        await session_transfer.export_archive_response(None, "session")
    assert archive.closed


def test_file_backed_archive_writer_and_reader_share_member_budgets(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.core.config.settings.DATA_DIR", str(tmp_path))
    folder = tmp_path / "adventures" / "sessions" / "session"
    folder.mkdir(parents=True)
    (folder / "portrait.png").write_bytes(b"fixture")
    with (tmp_path / "export.ads").open("w+b") as output:
        pack_export_ads_to({"value": "saved"}, "session", output)
        assert output.tell() == 0
        with zipfile.ZipFile(output) as archive:
            archive_safety.validate_archive(archive)
            assert archive.read("assets/portrait.png") == b"fixture"
        monkeypatch.setattr(archive_safety, "MAX_ENTRY_BYTES", 6)
        with pytest.raises(SessionArchiveLimitError):
            pack_export_ads_to({}, "session", output)


def test_file_backed_writer_limits_zip_overhead_and_member_count(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.core.config.settings.DATA_DIR", str(tmp_path))
    with (tmp_path / "export.ads").open("w+b") as output:
        monkeypatch.setattr(archive_safety, "MAX_UPLOAD_BYTES", 100)
        with pytest.raises(SessionArchiveLimitError, match="upload size budget"):
            pack_export_ads_to({}, "session", output)
        assert output.seek(0, 2) <= 100
        monkeypatch.setattr(archive_safety, "MAX_UPLOAD_BYTES", 10000)
        monkeypatch.setattr(archive_safety, "MAX_ENTRIES", 0)
        with pytest.raises(SessionArchiveLimitError, match="safety budget"):
            pack_export_ads_to({}, "session", output)


def test_shared_archive_and_narrow_https_proxy_limits_agree():
    assert archive_safety.MAX_UPLOAD_BYTES == 2 * 1024**3
    assert archive_safety.MAX_ENTRY_BYTES == 50 * 1024**2
    assert archive_safety.MAX_ENTRIES == 1000
    config = (Path(__file__).parents[1] / "nginx" / "nginx.conf").read_text()
    redirect, secure = config.split("# HTTPS server", maxsplit=1)
    assert "client_max_body_size 2049M" not in redirect
    upload = re.search(r"location = /api/adventures/sessions/import\s*\{([^}]+)\}", secure)
    assert upload is not None
    assert "proxy_pass http://taleweaver:8000" in upload[1]
    body_limit = int(re.search(r"client_max_body_size (\d+)M", upload[1])[1]) * 1024**2
    assert body_limit == archive_safety.MAX_UPLOAD_BYTES + 1024**2
    assert "client_max_body_size 50M" in secure


def test_uncompressed_total_accepts_exact_shared_budget_then_rejects_excess():
    infos = []
    sizes = [archive_safety.MAX_ENTRY_BYTES] * 40 + [48 * 1024**2]
    for index, size in enumerate(sizes):
        info = zipfile.ZipInfo(f"assets/{index}.png")
        info.file_size = info.compress_size = size
        infos.append(info)
    archive = SimpleNamespace(infolist=lambda: infos)
    archive_safety.validate_archive(archive)
    infos[-1].file_size += 1
    infos[-1].compress_size += 1
    with pytest.raises(ValueError, match="unpacked size budget"):
        archive_safety.validate_archive(archive)
