"""Regression coverage for archive isolation and simulation integrity."""

import io
import zipfile

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.core.config import settings
from backend.engine.living_world.foreground import check
from backend.engine.living_world.schema import Event, Settings, Simulation
from backend.engine.living_world.state import save
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter, _extract_assets
from backend.main import SafeStaticFiles
from backend.models.session_state import SessionState
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_living_world import demo, seed


async def test_internal_json_is_not_public(tmp_path):
    (tmp_path / "inference-reservations.json").write_text('{"audit-marker":true}')
    app = FastAPI()
    app.mount("/data", SafeStaticFiles(directory=str(tmp_path)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://audit") as client:
        result = await client.get("/data/inference-reservations.json")
    assert result.status_code == 403


async def test_archive_assets_reject_html_and_javascript(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("assets/page.html", '<script src="proof.js"></script>')
        z.writestr("assets/proof.js", "window.auditProof = true;")
    with (
        zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as z,
        pytest.raises(ValueError, match="assets must be"),
    ):
        _extract_assets(z, "audit-session")
    app = FastAPI()
    app.mount("/data", SafeStaticFiles(directory=str(tmp_path)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://audit") as client:
        html = await client.get("/data/adventures/sessions/audit-session/page.html")
        script = await client.get("/data/adventures/sessions/audit-session/proof.js")
    assert html.status_code == script.status_code == 403


async def test_ads_roundtrip_preserves_living_world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    async with TestSessionLocal() as db:
        user, state = await seed(db)
        save(state, demo())
        await db.commit()
        archive = await SessionExporter.export_ads(db, state.session_id)
        sid = await SessionImporter.import_ads(db, archive, user.id)
        assert sid
        restored = await db.scalar(select(SessionState).where(SessionState.session_id == sid))
        assert restored.living_world is not None
        assert restored.living_world["timeline"] != state.living_world["timeline"]
        assert restored.living_world["events"] == state.living_world["events"]


async def test_ads_import_detaches_private_foreign_template(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    async with TestSessionLocal() as db:
        owner, state = await seed(db)
        other = User(
            id="audit-other", username="audit-other", hashed_password="unused", role="user"
        )
        db.add(other)
        await db.commit()
        archive = await SessionExporter.export_ads(db, state.session_id)
        sid = await SessionImporter.import_ads(db, archive, other.id)
        assert sid
        restored = await db.scalar(select(SessionState).where(SessionState.session_id == sid))
        assert restored.user_id != owner.id
        assert restored.template_id is None


async def test_waiting_decision_at_cursor_blocks_foreground():
    async with TestSessionLocal() as db:
        user, state = await seed(db)
        sim = Simulation(
            settings=Settings(living_world_enabled=True, mode="CATCH_UP"),
            status="WAITING_FOR_LLM",
            events=[Event(event_id="blocked", due=0, kind="DECISION", status="WAITING_FOR_LLM")],
        )
        save(state, sim)
        await db.commit()
        from backend.engine.visual_novel.concurrency import SessionBusyError

        with pytest.raises(SessionBusyError):
            await check(db, state.session_id, user.id)


def test_ads_assets_enforce_compression_ratio_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    buffer = io.BytesIO()
    payload = b"0" * (4 * 1024 * 1024)
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("assets/compressed.bin", payload)
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as z:
        info = z.getinfo("assets/compressed.bin")
        assert info.file_size / info.compress_size > 500
        with pytest.raises(ValueError, match="compression ratio"):
            _extract_assets(z, "audit-ratio")
    assert not (tmp_path / "adventures/sessions/audit-ratio").exists()


def test_engine_leaf_import_works_independently():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "from backend.engine.session_importer import SessionImporter"],
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "filename", ["inference-reservations.json.tmp", "notes.txt", "page.html", "script.js"]
)
async def test_runtime_and_executable_files_are_not_public(tmp_path, filename):
    (tmp_path / filename).write_text("private")
    app = FastAPI()
    app.mount("/data", SafeStaticFiles(directory=str(tmp_path)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://audit") as client:
        result = await client.get("/data/" + filename)
    assert result.status_code == 403


async def test_svg_media_retains_sandbox_through_security_middleware(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr("backend.utils.media_access.authorize_media", AsyncMock())
    from backend.main import add_security_headers

    (tmp_path / "image.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    )
    app = FastAPI()
    app.middleware("http")(add_security_headers)
    app.mount("/data", SafeStaticFiles(directory=str(tmp_path)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://audit") as client:
        result = await client.get("/data/image.svg")
    assert result.status_code == 200
    assert result.headers["content-type"].startswith("image/svg+xml")
    assert result.headers["content-security-policy"].startswith("sandbox; default-src 'none'")
    assert result.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("public", [True, False])
async def test_ads_links_accessible_templates(tmp_path, monkeypatch, public):
    from backend.models.adventure_template import AdventureTemplate

    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    async with TestSessionLocal() as db:
        user, state = await seed(db)
        template = await db.get(AdventureTemplate, state.template_id)
        template.is_ready = public
        if not public:
            template.owner_id = user.id
        await db.commit()
        archive = await SessionExporter.export_ads(db, state.session_id)
        sid = await SessionImporter.import_ads(db, archive, user.id)
        restored = await db.scalar(select(SessionState).where(SessionState.session_id == sid))
        assert restored.template_id == template.id


async def test_failed_ads_import_removes_extracted_files(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    async with TestSessionLocal() as db:
        user, state = await seed(db)
        archive = await SessionExporter.export_ads(db, state.session_id)
        buffer = io.BytesIO(archive)
        with zipfile.ZipFile(buffer, "a") as packed:
            packed.writestr("assets/image.png", b"passive test media")
        monkeypatch.setattr(
            "backend.engine.session_importer.import_summaries",
            AsyncMock(side_effect=ValueError("Invalid summary fixture")),
        )
        assert await SessionImporter.import_ads(db, buffer.getvalue(), user.id) is None
    assert list((tmp_path / "adventures/sessions").iterdir()) == []


@pytest.mark.parametrize(
    "name", ["assets/../../escape.png", "assets\\escape.png", "/assets/escape.png"]
)
def test_archive_paths_must_be_relative_and_contained(name):
    from backend.engine.archive_safety import validate_archive

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, b"media")
    with (
        zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive,
        pytest.raises(ValueError, match="path"),
    ):
        validate_archive(archive)
