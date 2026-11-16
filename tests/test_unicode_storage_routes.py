"""Multilingual legacy IDs and asset names across upload/copy/export/audio paths."""

import io
import zipfile
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from sqlalchemy import select

from backend.api.routes.config_api import _normalize_catalog
from backend.core.config import settings
from backend.engine.manifest_apply.assets import copy_source_asset_to_current_adventure
from backend.engine.media_engine import MediaEngine
from backend.engine.tts_helpers import _write_audio_file
from backend.engine.world_generator import GameMasterLLM, WorldGenerator
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.models.world_entity import WorldScene
from backend.utils.download_headers import attachment_disposition
from backend.utils.path_security import data_url_to_local_path
from tests.conftest import TestSessionLocal

LEGACY_ID = "одинокий-путник-ab12cd34"
REAL_GENERATE_WORLD = WorldGenerator.generate_world


@pytest.fixture
async def legacy_world(auth_client, tmp_path, monkeypatch):
    # Also cover a localized installation/data root containing a space.
    data = tmp_path / "Данные игры"
    data.mkdir()
    monkeypatch.setattr(settings, "DATA_DIR", str(data))
    folder = data / "adventures" / "library" / LEGACY_ID / "visuals"
    folder.mkdir(parents=True)
    image = folder / "портрет.png"
    Image.new("RGB", (32, 48), color="blue").save(image)
    url = f"/data/adventures/library/{LEGACY_ID}/visuals/портрет.png"
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        db.add(
            AdventureTemplate(
                id=LEGACY_ID,
                title="Одинокий путник",
                owner_id=user.id,
                image_url=url,
                is_ready=True,
            )
        )
        db.add(
            WorldScene(
                id="FOREST",
                template_id=LEGACY_ID,
                label="Лес",
                description="Тихий лес.",
                image_url=url,
            )
        )
        await db.commit()
    return image, url


async def test_legacy_adventure_archive_keeps_unicode_assets(auth_client, legacy_world):
    image, _ = legacy_world
    response = await auth_client.get(f"/api/adventures/{LEGACY_ID}/export/adz")
    assert response.status_code == 200, response.text[:300]
    header = response.headers["content-disposition"]
    assert header.isascii()
    message = Message()
    message["Content-Disposition"] = header
    assert message.get_filename() == f"adventure_{LEGACY_ID}.adz"
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert image.read_bytes() in [bundle.read(name) for name in bundle.namelist()]


@pytest.mark.parametrize("route", ["data", "visual"])
async def test_upload_to_legacy_adventure(auth_client, legacy_world, route):
    image, _ = legacy_world
    files = {"file": ("рисунок.png", image.read_bytes(), "image/png")}
    if route == "data":
        response = await auth_client.post(
            "/api/data/image", params={"type": "adventure", "adventure_id": LEGACY_ID}, files=files
        )
    else:
        response = await auth_client.post(
            f"/api/adventures/{LEGACY_ID}/visuals/upload",
            data={"target_type": "cover", "target_id": LEGACY_ID},
            files=files,
        )
    assert response.status_code == 200, response.text
    url = response.json().get("url") or response.json().get("image_url")
    path = Path(data_url_to_local_path(url))
    assert path.is_file()
    assert LEGACY_ID in path.parts
    assert path.name.isascii()


async def test_thumbnail_of_imported_unicode_filename(legacy_world):
    image, _ = legacy_world
    thumbnail = await MediaEngine._generate_thumbnail(str(image))
    assert thumbnail and Path(thumbnail).is_file()
    assert Path(thumbnail).parent == image.parent


def test_source_image_reuse_keeps_unicode_filename(legacy_world):
    image, url = legacy_world
    copied = copy_source_asset_to_current_adventure(url, template_id="target", entity_type="npc")
    assert copied
    assert Path(data_url_to_local_path(copied)).read_bytes() == image.read_bytes()
    assert "/target/" in copied


def test_speech_stays_in_legacy_session_directory(legacy_world):
    url = _write_audio_file(b"audio-fixture", None, LEGACY_ID, "wav")
    assert url.startswith(f"/data/adventures/sessions/{LEGACY_ID}/tts/")
    assert Path(data_url_to_local_path(url)).read_bytes() == b"audio-fixture"


async def test_clone_legacy_adventure_preserves_visuals(auth_client, legacy_world):
    image, _ = legacy_world
    response = await auth_client.post(f"/api/adventures/{LEGACY_ID}/duplicate", json={})
    assert response.status_code == 201, response.text
    clone = response.json()
    assert clone["id"].isascii()
    assert Path(data_url_to_local_path(clone["image_url"])).read_bytes() == image.read_bytes()


def test_download_headers_cannot_inject_raw_control_characters():
    header = attachment_disposition('имя"\r\nX-Injected: yes.ads')
    assert header.isascii()
    assert "\r" not in header and "\n" not in header
    assert "%0D%0A" in header


async def test_world_generation_accepts_legacy_source_and_target(legacy_world, monkeypatch):
    manifest = {"scenes": [], "npcs": [], "objects": [], "exits": []}
    result = SimpleNamespace(**manifest, model_dump=manifest.copy)
    llm = SimpleNamespace(
        provider="ollama", model="mock", aexecute_complex_task=AsyncMock(return_value=result)
    )
    monkeypatch.setattr(GameMasterLLM, "for_role", lambda *args, **kwargs: llm)
    generate = AsyncMock(return_value=result)
    monkeypatch.setattr("backend.engine.staged_world.generate_manifest", generate)
    apply = AsyncMock()
    monkeypatch.setattr("backend.engine.world_manifest_applier.apply_manifest", apply)
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        await REAL_GENERATE_WORLD(
            db,
            user,
            LEGACY_ID,
            "Одинокий путник",
            "История в лесу",
            cover_source_adventure_id=LEGACY_ID,
        )
    generate.assert_awaited_once()
    assert generate.call_args.kwargs["template_id"] == LEGACY_ID
    assert generate.call_args.kwargs["llm"] is llm
    apply.assert_awaited_once()
    assert apply.call_args.args[1] == LEGACY_ID
    assert apply.call_args.kwargs["source_assets"]["cover"] == legacy_world[1]


@pytest.mark.parametrize("route", ["data", "visual"])
async def test_upload_cannot_escape_with_unicode_traversal(auth_client, legacy_world, route):
    image, _ = legacy_world
    files = {"file": ("рисунок.png", image.read_bytes(), "image/png")}
    if route == "data":
        response = await auth_client.post(
            "/api/data/image", params={"type": "adventure", "adventure_id": "../лес"}, files=files
        )
    else:
        response = await auth_client.post(
            f"/api/adventures/{LEGACY_ID}/visuals/upload",
            data={"target_type": "cover", "target_id": "../лес"},
            files=files,
        )
    assert response.status_code == 400, response.text


def test_old_catalog_names_without_ids_remain_distinct_and_stable():
    entries = [
        {"name": "Акварель"},
        {"name": "Нуар"},
        {"name": "森"},
        {"id": "fixed", "name": "Тон"},
    ]
    first = _normalize_catalog(entries, fallback=[])
    second = _normalize_catalog(entries, fallback=[])
    assert first == second
    assert len({item["id"] for item in first}) == len(entries)
    assert first[-1]["id"] == "fixed"
    assert [item["name"] for item in first] == [item["name"] for item in entries]


async def test_catalog_image_upload_accepts_legacy_unicode_id(auth_client, legacy_world):
    image, _ = legacy_world
    response = await auth_client.post(
        "/api/settings/catalog/upload",
        data={"catalog_type": "styles", "target_id": "акварель"},
        files={"file": ("рисунок.png", image.read_bytes(), "image/png")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "success", response.text
    assert Path(data_url_to_local_path(response.json()["image_url"])).is_file()
