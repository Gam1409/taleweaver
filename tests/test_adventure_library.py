"""Catalog transport, identity and non-destructive installation contracts."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.core.config import settings
from backend.engine.adventure_identity import stable_origin_id
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.services.adventure_library import catalog, installer
from backend.services.adventure_library.models import LibraryEntry

ORIGIN = "fdc871d3-3ad1-4293-bd21-05a73ad765da"
BASE = "https://catalog.example.test/main"


def entry(**changes):
    return LibraryEntry(
        **(
            {
                "id": ORIGIN,
                "slug": "forest",
                "title": "Forest",
                "version": "2.0",
                "files": ["adventure.adv", "assets/cover.png"],
            }
            | changes
        )
    )


def manifest(**changes):
    return {
        "format": "TaleWeaver",
        "version": "1.3",
        "adventure": {
            "origin_id": ORIGIN,
            "title": "Forest",
            "version": "2.0",
            "rule_enforcement_mode": "rpg",
            "image_url": "assets/cover.png",
            **changes,
        },
        "protagonist": {"name": "Hero"},
        "scenes": [{"id": "START", "label": "Forest", "description": "Trees"}],
        "objects": [],
        "npcs": [],
        "exits": [],
    }


def payload_files(payload=None):
    return {
        "adventure.adv": json.dumps(payload or manifest()).encode(),
        "assets/cover.png": b"new-cover",
    }


@pytest.fixture(autouse=True)
def isolated_catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ADVENTURE_LIBRARY_URL", BASE)
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    catalog.LibraryService().invalidate()
    yield
    catalog.LibraryService().invalidate()


@pytest.mark.parametrize(
    "path",
    [
        "../secret",
        "/assets/x",
        "assets/../x",
        "assets//x",
        "assets/a%2fb",
        "assets/a?b",
        "assets/a\\b",
        "assets/a\x00b",
    ],
)
def test_remote_paths_cannot_escape_catalog_or_archive(path):
    with pytest.raises(ValidationError):
        entry(files=["adventure.adv", path])


def test_index_requires_canonical_uuid_and_unique_file_paths():
    assert entry(id=ORIGIN.upper()).id == ORIGIN
    with pytest.raises(ValidationError):
        entry(id="title-is-not-identity")
    with pytest.raises(ValidationError):
        entry(files=["adventure.adv", "adventure.adv"])


def test_catalog_entry_and_file_counts_are_bounded(monkeypatch):
    monkeypatch.setattr(catalog, "MAX_INDEX_ENTRIES", 1)
    with pytest.raises(catalog.LibraryError, match="too many"):
        catalog.parse_library({"schema": 1, "adventures": [{}, {}]})
    with pytest.raises(ValidationError):
        entry(files=["adventure.adv", *[f"assets/file-{index}.png" for index in range(1000)]])


@pytest.mark.parametrize(
    "changes", [{"origin_id": str(uuid4())}, {"version": "9.0"}, {"title": "Other"}]
)
def test_downloaded_manifest_must_match_selected_identity_version_and_title(changes):
    with pytest.raises(installer.AdventureInstallError, match="differs from the catalog"):
        installer.convert_files(entry(), payload_files(manifest(**changes)))


def test_basename_collisions_cannot_overwrite_other_assets():
    files = payload_files() | {"assets/nested/cover.png": b"collision"}
    with pytest.raises(installer.AdventureInstallError, match="duplicate filenames"):
        installer.convert_files(entry(), files)


@pytest.mark.parametrize("identity", [5, None, {"bad": "identity"}])
def test_malformed_manifest_identity_is_a_validation_failure(identity):
    with pytest.raises(installer.AdventureInstallError):
        installer.convert_files(entry(), payload_files(manifest(origin_id=identity)))


@pytest.mark.asyncio
async def test_index_cache_is_scoped_by_url_in_memory_and_on_disk(monkeypatch):
    index = {"schema": 1, "adventures": [entry().model_dump()]}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=index))
    ) as client:
        service = catalog.LibraryService(client)
        assert (await service.get_library()).adventures[0].id == ORIGIN
    old_cache = catalog.cache_path()
    assert old_cache.exists()
    monkeypatch.setattr(settings, "ADVENTURE_LIBRARY_URL", "https://other.example.test/catalog")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    ) as client:
        with pytest.raises(catalog.LibraryError):
            await catalog.LibraryService(client).get_library()
    assert catalog.cache_path() != old_cache
    monkeypatch.setattr(settings, "ADVENTURE_LIBRARY_URL", BASE)
    service.invalidate()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    ) as client:
        fallback = catalog.LibraryService(client)
        assert (await fallback.get_library()).adventures[0].id == ORIGIN
        assert fallback.is_stale()


@pytest.mark.asyncio
async def test_index_response_and_aggregate_download_are_bounded(monkeypatch):
    monkeypatch.setattr(catalog, "MAX_INDEX_BYTES", 10)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 11))
    ) as client:
        with pytest.raises(catalog.LibraryError, match="limit"):
            await catalog.LibraryService(client).get_library()
    monkeypatch.setattr(settings, "ADVENTURE_DOWNLOAD_MAX_BYTES", 15)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 10))
    ) as client:
        with pytest.raises(catalog.LibraryError, match="limit"):
            await installer.fetch_files(entry(), client)


@pytest.mark.asyncio
async def test_catalog_downloads_never_follow_redirects():
    requests = []

    def redirect(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://other.example.test/secret"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(redirect), follow_redirects=True
    ) as client:
        with pytest.raises(catalog.LibraryError, match="302"):
            await installer.fetch_files(entry(files=["adventure.adv"]), client)
    assert requests == [BASE + "/forest/adventure.adv"]


@pytest.mark.asyncio
@pytest.mark.parametrize("same_origin", [True, False])
async def test_real_import_preserves_existing_template_session_and_assets(
    db_session, monkeypatch, tmp_path, same_origin
):
    user = User(username="catalog-owner", hashed_password="unused")
    db_session.add(user)
    await db_session.flush()
    avatar = Avatar(name="Hero", user_id=user.id)
    db_session.add(avatar)
    old = AdventureTemplate(
        id="old-template",
        title="Forest",
        owner_id=user.id,
        origin_id=ORIGIN if same_origin else str(uuid4()),
        version="1.0",
    )
    db_session.add(old)
    await db_session.flush()
    session = GameSession(user_id=user.id, avatar_id=avatar.id, template_id=old.id)
    db_session.add(session)
    await db_session.commit()
    old_asset = tmp_path / "adventures" / "library" / old.id / "cover.png"
    old_asset.parent.mkdir(parents=True)
    old_asset.write_bytes(b"old-cover")
    monkeypatch.setattr(installer, "fetch_files", AsyncMock(return_value=payload_files()))
    monkeypatch.setattr("backend.engine.world_generator.WorldGenerator.apply_manifest", AsyncMock())
    monkeypatch.setattr("backend.engine.media_engine.MediaEngine.ensure_thumbnails", AsyncMock())

    template_id = await installer.install_entry(db_session, entry(), owner_id=user.id)

    assert template_id != old.id
    assert (await db_session.get(AdventureTemplate, old.id)).version == "1.0"
    await db_session.refresh(session)
    assert session.template_id == old.id and old_asset.read_bytes() == b"old-cover"
    imported = await db_session.get(AdventureTemplate, template_id)
    assert imported.origin_id == ORIGIN and imported.version == "2.0"
    assert (
        tmp_path / "adventures" / "library" / template_id / "cover.png"
    ).read_bytes() == b"new-cover"
    repeated = await installer.install_entry(db_session, entry(), owner_id=user.id)
    assert repeated == template_id
    installer.fetch_files.assert_awaited_once()


@pytest.mark.asyncio
async def test_owner_isolation_and_exported_local_identity_detection(db_session, monkeypatch):
    first, second = (
        User(username="one", hashed_password="unused"),
        User(username="two", hashed_password="unused"),
    )
    db_session.add_all([first, second])
    await db_session.flush()
    local = AdventureTemplate(title="Forest", owner_id=first.id, version="2.0")
    db_session.add(local)
    await db_session.flush()
    selected = entry(id=stable_origin_id(local))
    assert await installer.owned_templates(db_session, first.id, [selected.id]) == [local]
    assert await installer.owned_templates(db_session, second.id, [selected.id]) == []
    fetch = AsyncMock(side_effect=AssertionError("Installed version needs no download"))
    monkeypatch.setattr(installer, "fetch_files", fetch)
    assert await installer.install_entry(db_session, selected, owner_id=first.id) == local.id
    fetch.assert_not_awaited()
    assert (
        await db_session.scalar(
            select(AdventureTemplate.origin_id).where(AdventureTemplate.id == local.id)
        )
        is None
    )
