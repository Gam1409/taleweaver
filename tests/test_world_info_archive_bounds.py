"""New source corpora obey the existing complete ADS reader budgets."""

import io
import zipfile

import pytest

from backend.core.config import settings
from backend.engine import archive_safety
from backend.engine.export_archives import SessionArchiveLimitError, pack_export_ads
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


async def test_repetitive_source_exports_to_an_archive_the_real_importer_accepts(
    auth_client, portrait_world
):
    source = "L" * 250_000
    uploaded = await auth_client.post(
        "/api/adventures/portrait-session/world-info/sources",
        data={"title": "Harbor notes"},
        files={"file": ("harbor.md", source.encode(), "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    exported = await auth_client.get("/api/adventures/sessions/portrait-session/export")
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        archive_safety.validate_archive(archive)
        info = archive.getinfo("session.json")
        assert info.file_size <= archive_safety.MAX_COMPRESSION_RATIO * max(1, info.compress_size)
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("harbor.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text


def test_whole_manifest_budget_includes_existing_state_and_new_knowledge(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(archive_safety, "MAX_ENTRY_BYTES", 1500)
    # Each section is below the entry budget; the complete manifest exceeds it.
    manifest = {"session_state": {"history": "H" * 800}, "world_info": {"content": "L" * 800}}
    with pytest.raises(SessionArchiveLimitError, match="manifest exceeds"):
        pack_export_ads(manifest, "fictional-session")


async def test_oversized_complete_session_export_returns_413_without_changing_saved_data(
    auth_client, portrait_world, monkeypatch
):
    original_limit = archive_safety.MAX_ENTRY_BYTES
    monkeypatch.setattr(archive_safety, "MAX_ENTRY_BYTES", 128)
    response = await auth_client.get("/api/adventures/sessions/portrait-session/export")
    assert response.status_code == 413
    assert response.json()["detail"] == "Session manifest exceeds the portable archive size budget."
    monkeypatch.setattr(archive_safety, "MAX_ENTRY_BYTES", original_limit)
    assert (
        await auth_client.get("/api/adventures/sessions/portrait-session/export")
    ).status_code == 200


def test_generated_asset_archive_still_rejects_existing_reader_budget_violations(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    folder = tmp_path / "adventures" / "sessions" / "fictional-session"
    folder.mkdir(parents=True)
    (folder / "unsafe.txt").write_text("An unsupported archive asset.")
    with pytest.raises(SessionArchiveLimitError, match="assets exceed"):
        pack_export_ads({}, "fictional-session")
