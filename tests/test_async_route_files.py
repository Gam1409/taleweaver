"""Requests retain their results while filesystem work runs outside the event loop."""

import json
import threading
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.routing import Mount

from backend.api.routes import config_api, users_api
from backend.api.routes.adventures import imports
from backend.core.config import settings
from backend.utils.static_media import SafeStaticFiles


@pytest.fixture
def import_directory(tmp_path):
    (tmp_path / "plain.adv").write_text(json.dumps({"title": "Plain", "origin_id": "a"}))
    with zipfile.ZipFile(tmp_path / "packed.adz", "w") as archive:
        archive.writestr(
            "adventure.adv", json.dumps({"adventure": {"title": "Packed"}, "origin_id": "b"})
        )
    (tmp_path / "broken.adv").write_text("invalid json")
    return tmp_path


def worker_spy(monkeypatch, module, name):
    original = getattr(module, name)
    caller_thread = threading.get_ident()
    calls = []

    def wrapped(*args, **kwargs):
        assert threading.get_ident() != caller_thread
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapped)
    return calls


@pytest.mark.asyncio
async def test_import_scan_offloads_reads_but_not_database(import_directory, monkeypatch):
    calls = worker_spy(monkeypatch, imports, "scan_import_candidates")
    caller_thread = threading.get_ident()

    async def execute(_query):
        assert threading.get_ident() == caller_thread
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: None))

    result = await imports._get_import_check_items(
        SimpleNamespace(execute=execute),
        "owner",
        [str(import_directory), str(import_directory / "missing")],
    )
    assert calls
    assert {(item.title, item.origin_id) for item in result} == {("Plain", "a"), ("Packed", "b")}
    assert not any(item.already_exists for item in result)


@pytest.mark.asyncio
async def test_uploads_offload_persistence(auth_client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    profile_calls = worker_spy(monkeypatch, users_api, "save_profile_image")
    catalog_calls = worker_spy(monkeypatch, config_api, "save_catalog_image")
    profile = await auth_client.post(
        "/api/users/me/profile-image", files={"file": ("portrait.png", b"portrait", "image/png")}
    )
    assert profile.status_code == 200, profile.text
    catalog = await auth_client.post(
        "/api/settings/catalog/upload",
        data={"catalog_type": "styles", "target_id": "test"},
        files={"file": ("tile.png", b"tile", "image/png")},
    )
    assert catalog.status_code == 200, catalog.text
    assert catalog.json()["status"] == "success"
    assert profile_calls and catalog_calls


@pytest.fixture
def static_directory(tmp_path):
    (tmp_path / "picture.png").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    (tmp_path / "private.json").write_text("{}")
    return tmp_path


@pytest.mark.asyncio
async def test_static_lookup_and_svg_sniffing_run_in_workers(static_directory, monkeypatch):
    from backend.utils import static_media

    media = SafeStaticFiles(directory=static_directory)
    lookups = worker_spy(monkeypatch, media, "lookup_path")
    sniffing = worker_spy(monkeypatch, static_media, "_is_svg")
    app = Starlette(routes=[Mount("/data", media)])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/data/picture.png")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/svg+xml"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in response.headers["content-security-policy"]
        assert (await client.get("/data/private.json")).status_code == 403
        assert (await client.get("/data/missing.png")).status_code == 404
    assert lookups and sniffing


@pytest.mark.asyncio
async def test_missing_thumbnail_is_generated(static_directory, monkeypatch):
    from backend.engine.media_engine import MediaEngine

    async def generate(source):
        # Delegate fixture file work just like the real thumbnail generator.
        from pathlib import Path

        from backend.utils.async_files import run_file_operation

        await run_file_operation(
            Path(source).with_name("picture_thumb.png").write_bytes, b"thumbnail"
        )

    generator = AsyncMock(side_effect=generate)
    monkeypatch.setattr(MediaEngine, "_generate_thumbnail", generator)
    app = Starlette(routes=[Mount("/data", SafeStaticFiles(directory=static_directory))])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/data/picture_thumb.png")
    assert response.status_code == 200
    assert response.content == b"thumbnail"
    generator.assert_awaited_once()


@pytest.mark.asyncio
async def test_sheet_reads_state_on_loop_and_resolves_paths_in_worker(monkeypatch):
    from backend.api.routes.adventures.logic import AdventureLogic
    from backend.api.routes.adventures.session_sheet import _sheet_profile_image

    caller_thread = threading.get_ident()

    class State:
        @property
        def entity_states(self):
            assert threading.get_ident() == caller_thread
            return {"__asset_snapshot__": {"protagonist": "/data/portrait.png"}}

    def resolve(candidate):
        assert threading.get_ident() != caller_thread
        assert candidate == "/data/portrait.png"
        return candidate

    monkeypatch.setattr(AdventureLogic, "resolve_existing_data_asset_url", resolve)
    avatar = SimpleNamespace(profile_image="/data/fallback.png")
    assert await _sheet_profile_image(None, avatar, State(), {}) == "/data/portrait.png"
