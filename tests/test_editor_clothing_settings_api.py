"""Existing adventure saves persist clothing preferences and fail atomically."""

from copy import deepcopy
from unittest.mock import AsyncMock

from backend.api.routes.adventures.editing import clothing_settings as endpoint
from backend.engine.clothing.editor_conversion import ClothingConversionError
from backend.engine.clothing.settings import with_clothing_settings
from backend.models.adventure_template import AdventureTemplate
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
BASE = "/api/adventures/portrait-template"


async def test_editor_save_enables_and_reload_reports_setting(
    auth_client, portrait_world, monkeypatch
):
    async def prepare(db, adventure, detailed, **kwargs):
        adventure.original_manifest = with_clothing_settings(adventure.original_manifest, detailed)

    prepare_mock = AsyncMock(side_effect=prepare)
    monkeypatch.setattr(endpoint, "apply_editor_clothing", prepare_mock)
    result = await auth_client.patch(
        BASE, json={"rule_enforcement_mode": "vn", "detailed_clothing": True}
    )
    assert result.status_code == 200, result.text
    assert result.json()["detailed_clothing"] is True
    assert (await auth_client.get(BASE)).json()["detailed_clothing"] is True
    prepare_mock.assert_awaited_once()
    assert prepare_mock.call_args.args[2] is True
    await auth_client.patch(BASE, json={"title": "Renamed"})
    prepare_mock.assert_awaited_once()


async def test_disabling_preserves_story_and_profiles(auth_client, portrait_world):
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "portrait-template")
        adventure.rule_enforcement_mode = "vn"
        manifest = {
            "clothing_settings": {"detailed": True},
            "npcs": [{"id": "MIRA", "visual_profile": {"version": 1, "worn": []}}],
        }
        adventure.original_manifest = deepcopy(manifest)
        await db.commit()
    result = await auth_client.patch(BASE, json={"detailed_clothing": False})
    assert result.status_code == 200, result.text
    assert result.json()["detailed_clothing"] is False
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "portrait-template")
        assert adventure.original_manifest["npcs"] == manifest["npcs"]
        assert adventure.original_manifest["clothing_settings"] == {"detailed": False}


async def test_conversion_failure_does_not_save_metadata(auth_client, portrait_world, monkeypatch):
    async def fail(db, adventure, *args, **kwargs):
        adventure.original_manifest = {"clothing_settings": {"detailed": True}}
        raise ClothingConversionError("model error")

    monkeypatch.setattr(endpoint, "apply_editor_clothing", fail)
    result = await auth_client.patch(
        BASE, json={"title": "Unsaved", "rule_enforcement_mode": "vn", "detailed_clothing": True}
    )
    assert result.status_code == 502
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "portrait-template")
        assert adventure.title == "Forest"
        assert not (adventure.original_manifest or {}).get("clothing_settings", {}).get("detailed")


async def test_invalid_mode_and_foreign_template_never_call_model(
    auth_client, portrait_world, monkeypatch
):
    prepare = AsyncMock()
    monkeypatch.setattr(endpoint, "apply_editor_clothing", prepare)
    invalid = await auth_client.patch(
        BASE, json={"rule_enforcement_mode": "rpg", "detailed_clothing": True}
    )
    assert invalid.status_code == 422
    missing = await auth_client.patch("/api/adventures/missing", json={"detailed_clothing": True})
    assert missing.status_code == 404
    prepare.assert_not_awaited()


async def test_leaving_vn_deactivates_detail(auth_client, portrait_world):
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "portrait-template")
        adventure.rule_enforcement_mode = "vn"
        adventure.original_manifest = with_clothing_settings({}, True)
        await db.commit()
    result = await auth_client.patch(BASE, json={"rule_enforcement_mode": "chat"})
    assert result.status_code == 200, result.text
    assert result.json()["detailed_clothing"] is False
