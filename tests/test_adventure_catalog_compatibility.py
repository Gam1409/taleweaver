"""Catalog conversion preserves supported awards, formats and existing story identities."""

import json
from copy import deepcopy

import httpx
import pytest

from backend.core.config import settings
from backend.engine.adventure_compat import (
    CompatibilityError,
    export_upstream_manifest,
    import_upstream_manifest,
)
from backend.engine.gameplay.world import AdventureLogic
from backend.services.adventure_library import installer
from backend.services.adventure_library.catalog import parse_library
from tests.test_adventure_library import BASE, ORIGIN, entry, manifest, payload_files


@pytest.mark.parametrize("earned", [False, True])
@pytest.mark.parametrize("version", ["1.3", "1.3.0", "1.3.1"])
def test_supported_catalog_award_and_format_preserve_content_without_granting_progress(
    earned, version
):
    source = manifest()
    source["version"] = version
    source["awards"] = [
        {
            "key": "FOUND_KEY",
            "title": "Found the key",
            "description": "A first discovery",
            "tier": "bronze",
            "requirement": "Find the key",
            "is_earned": earned,
        }
    ]
    before = deepcopy(source)
    converted = import_upstream_manifest(source)
    assert source == before
    assert converted["version"] == version
    assert converted["awards"] == before["awards"]
    public, _ = export_upstream_manifest(converted)
    assert public["awards"] == before["awards"]
    shown = AdventureLogic.build_awards_payload([], public["awards"], "template")
    assert next(row for row in shown if row["key"] == "FOUND_KEY")["is_earned"] is False


@pytest.mark.parametrize("version", ["1.3.2", "1.4", "2.0"])
def test_unaudited_formats_remain_blocked(version):
    source = manifest()
    source["version"] = version
    with pytest.raises(CompatibilityError, match="formats"):
        import_upstream_manifest(source)


def test_supported_patch_does_not_bypass_existing_feature_checks():
    source = manifest()
    source["version"] = "1.3.1"
    source["scripts"] = [{"code": "tw.dialog('Pick an answer')"}]
    with pytest.raises(CompatibilityError, match="API unavailable"):
        import_upstream_manifest(source)


@pytest.mark.parametrize("identity", ["original-story", "Chapter-A", "История-01"])
def test_legacy_origin_is_kept_in_catalog_and_converted_manifest(identity):
    raw = entry().model_dump() | {"id": identity}
    catalog = parse_library({"schema": 1, "adventures": [raw]})
    assert len(catalog.adventures) == 1
    selected = catalog.adventures[0]
    converted = installer.convert_files(selected, payload_files(manifest(origin_id=identity)))
    assert json.loads(converted["adventure.adv"])["adventure"]["origin_id"] == identity
    assert selected.id == identity


def test_distinct_legacy_identity_must_not_match_by_title_or_case():
    selected = entry().model_copy(update={"id": "Chapter-A"})
    with pytest.raises(installer.AdventureInstallError, match="differs"):
        installer.convert_files(selected, payload_files(manifest(origin_id="chapter-a")))


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["original-story", "Chapter-A", "История-01", ORIGIN.upper()])
async def test_legacy_installed_identity_is_owner_scoped(db_session, identity):
    from backend.models.adventure_template import AdventureTemplate
    from backend.models.user import User

    user = User(username="legacy-owner", hashed_password="unused")
    db_session.add(user)
    await db_session.flush()
    template = AdventureTemplate(
        title="Old title", owner_id=user.id, origin_id=identity, version="2.0"
    )
    db_session.add(template)
    await db_session.flush()
    selected = entry(id=identity)
    assert await installer.owned_templates(db_session, user.id, [selected.id]) == [template]
    assert await installer.install_entry(db_session, selected, owner_id=user.id) == template.id
    assert template.origin_id == identity


@pytest.mark.asyncio
async def test_different_legacy_case_is_not_an_installed_release(db_session):
    from backend.models.adventure_template import AdventureTemplate
    from backend.models.user import User

    user = User(username="case-owner", hashed_password="unused")
    db_session.add(user)
    await db_session.flush()
    template = AdventureTemplate(
        title="Forest", owner_id=user.id, origin_id="chapter-a", version="2.0"
    )
    db_session.add(template)
    await db_session.flush()
    assert await installer.owned_templates(db_session, user.id, ["Chapter-A"]) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["version", "script", "identity", "asset_names"])
async def test_incompatible_release_fails_before_any_asset_download(monkeypatch, failure):
    monkeypatch.setattr(settings, "ADVENTURE_LIBRARY_URL", BASE)
    source = manifest()
    files = ["adventure.adv", "assets/cover.png"]
    if failure == "version":
        source["version"] = "1.4"
    elif failure == "script":
        source["version"] = "1.3.1"
        source["scripts"] = [{"code": "tw.dialog('Question')"}]
    elif failure == "identity":
        source["adventure"]["origin_id"] = "another-story"
    else:
        files.append("assets/nested/cover.png")
    requested = []

    def response(request):
        requested.append(str(request.url))
        return httpx.Response(200, json=source)

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        with pytest.raises(installer.AdventureInstallError):
            await installer.fetch_files(entry(files=files), client)
    assert requested == [BASE + "/forest/adventure.adv"]


@pytest.mark.asyncio
async def test_preflight_downloads_blueprint_once_and_preserves_raw_asset_bytes(monkeypatch):
    monkeypatch.setattr(settings, "ADVENTURE_LIBRARY_URL", BASE)
    files = payload_files()
    requested = []

    def response(request):
        path = str(request.url).removeprefix(BASE + "/forest/")
        requested.append(path)
        return httpx.Response(200, content=files[path])

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        assert await installer.fetch_files(entry(), client) == files
    assert requested == ["adventure.adv", "assets/cover.png"]


@pytest.mark.asyncio
async def test_real_catalog_install_and_export_keep_legacy_identity_awards_and_npc_seeds(
    db_session, monkeypatch, tmp_path
):
    from unittest.mock import AsyncMock

    from sqlalchemy import func, select

    from backend.engine.adventure_exporter import AdventureExporter
    from backend.models.game_session import GameSession
    from backend.models.user import User

    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    source = manifest(
        origin_id="original-story",
        language="en",
        can_damage_npcs=False,
        npcs_can_damage_protagonist=False,
    )
    source["version"] = "1.3.1"
    source["scenes"][0]["image_url"] = "assets/cover.png"
    source["protagonist"]["profile_image"] = "assets/cover.png"
    seed = {"schema_version": 1, "initial_state": {"situation": "Waiting by the door"}}
    source["npcs"] = [
        {
            "id": "GUIDE",
            "name": "Guide",
            "description": "A guide waiting by the door.",
            "start_scene_id": "START",
            "image_url": "assets/cover.png",
            "metadata_json": {"agent_runtime": seed},
        }
    ]
    source["extensions"] = {"agent_runtime": {"schema_version": 1}}
    source["init_script"] = "def greeting():\n    return 'Welcome'"
    source["scripts"] = [
        {
            "id": "WELCOME",
            "target_id": "START",
            "trigger": "on_enter_scene",
            "code": "tw.narrate('Welcome')",
        }
    ]
    source["awards"] = [
        {"key": "FOUND_KEY", "title": "Discovery", "tier": "bronze", "is_earned": True}
    ]
    before = deepcopy(source)
    monkeypatch.setattr(installer, "fetch_files", AsyncMock(return_value=payload_files(source)))
    for method in ("generate_placeholder", "generate_svg_placeholder", "ensure_thumbnails"):
        monkeypatch.setattr(
            f"backend.engine.media_engine.MediaEngine.{method}",
            AsyncMock(return_value="/data/fake.svg"),
        )
    user = User(username="catalog-roundtrip", hashed_password="unused")
    db_session.add(user)
    await db_session.flush()
    template_id = await installer.install_entry(
        db_session, entry(id="original-story"), owner_id=user.id
    )
    exported = await AdventureExporter.build_full_manifest(db_session, template_id)
    assert exported["adventure"]["origin_id"] == "original-story"
    assert exported["adventure"]["language"] == "en"
    assert exported["adventure"]["can_damage_npcs"] is False
    assert exported["adventure"]["npcs_can_damage_protagonist"] is False
    assert exported["init_script"] == source["init_script"]
    assert exported["scripts"] == source["scripts"]
    assert exported["extensions"] == source["extensions"]
    assert exported["npcs"][0]["metadata_json"]["agent_runtime"] == seed
    assert exported["awards"][0]["key"] == "FOUND_KEY"
    assert source == before
    assert not user.earned_awards
    assert await db_session.scalar(select(func.count()).select_from(GameSession)) == 0
