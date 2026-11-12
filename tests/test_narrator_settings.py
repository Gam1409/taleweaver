"""Narrator presentation survives boundaries without replacing character instructions."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.core.narrator_voices import default_narrator_voices
from backend.engine.narrator.prompts import narration_style_block
from backend.engine.narrator.settings import (
    MANIFEST_KEY,
    SETTINGS_KEY,
    NarratorSettings,
    manifest_settings,
    preserve_settings,
    read_settings,
)
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.adventure_template import AdventureTemplate
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldScene
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
BASE = "/api/adventures/portrait-session/narrator-settings"
DEFAULTS = "/api/adventures/portrait-template/narrator-defaults"
BRIEF = "/api/adventures/portrait-template/world-brief"


def choice():
    return {"voice": default_narrator_voices()[1], "verbosity": "rich", "flow": "gentle"}


@pytest.mark.asyncio
async def test_failed_generation_brief_is_editable_and_reference_changes_drop_cache(
    auth_client, portrait_world
):
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "portrait-template")
        adventure.is_ready = False
        adventure.creation_status = "Failed"
        adventure.generation_run_id = "old-run"
        adventure.original_manifest = {
            MANIFEST_KEY: choice(),
            "world_brief": {
                "setting": "Orbital city",
                "references": [{"url": "https://example.org/"}],
            },
            "world_brief_sources": {"fingerprint": "old", "entries": []},
        }
        await db.commit()
    response = await auth_client.get(BRIEF)
    assert response.status_code == 200
    brief = response.json()
    brief["references"] = [{"excerpt": "Relevant canon supplied by the author."}]
    assert (await auth_client.put(BRIEF, json=brief)).status_code == 200
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "portrait-template")
        assert "world_brief_sources" not in adventure.original_manifest
        assert adventure.original_manifest[MANIFEST_KEY] == choice()
        adventure.creation_status = "Generating..."
        await db.commit()
    assert (await auth_client.put(BRIEF, json=brief)).status_code == 409


@pytest.mark.asyncio
async def test_world_brief_rejects_foreign_and_private_sources(auth_client, portrait_world):
    assert (
        await auth_client.put(BRIEF, json={"references": [{"url": "http://127.0.0.1/"}]})
    ).status_code == 422
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "portrait-template")
        adventure.owner_id = None
        await db.commit()
    assert (await auth_client.get(BRIEF)).status_code == 404
    assert (await auth_client.put(BRIEF, json={})).status_code == 404


def test_neutral_legacy_settings_add_no_prompt_or_model_calls():
    assert narration_style_block(SimpleNamespace(entity_states={})) == ""
    assert manifest_settings(None) == NarratorSettings()
    assert (
        read_settings(SimpleNamespace(entity_states={SETTINGS_KEY: {"invalid": True}}))
        == NarratorSettings()
    )


def test_frozen_defaults_override_and_author_protection():
    manifest = {MANIFEST_KEY: choice(), "clothing_settings": {"detailed": True}}
    before = deepcopy(manifest)
    state = SimpleNamespace(
        entity_states={"__manifest_snapshot__": {"original_manifest": manifest}}
    )
    assert read_settings(state).verbosity == "rich"
    state.entity_states[SETTINGS_KEY] = {"voice": None, "verbosity": "terse"}
    assert read_settings(state).voice is None
    assert read_settings(state).verbosity == "terse"
    generated = preserve_settings(
        {MANIFEST_KEY: {"verbosity": "epic"}}, SimpleNamespace(original_manifest=manifest)
    )
    assert generated[MANIFEST_KEY] == choice()
    assert manifest == before


def test_catalog_and_prompt_keep_samples_and_character_decisions_separate():
    for voice in default_narrator_voices():
        NarratorSettings.model_validate({"voice": voice})
    state = SimpleNamespace(entity_states={SETTINGS_KEY: choice()})
    prompt = narration_style_block(state)
    assert choice()["voice"]["instruction"] in prompt
    assert choice()["voice"]["sample"] not in prompt
    assert "not to every NPC's speech or psychology" in prompt
    assert "configured pace" in prompt


@pytest.mark.asyncio
async def test_owner_save_keeps_other_session_json_and_reload(auth_client, portrait_world):
    response = await auth_client.put(BASE, json=choice())
    assert response.status_code == 200
    assert (await auth_client.get(BASE)).json()["settings"] == choice()
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.entity_states[SETTINGS_KEY] == choice()
        assert state.current_scene_id == "TOWER"
    with session_write_lease("portrait-session"):
        assert (await auth_client.put(BASE, json=choice())).status_code == 409


@pytest.mark.asyncio
async def test_adventure_defaults_do_not_modify_existing_session(auth_client, portrait_world):
    previous = (await auth_client.get(BASE)).json()["settings"]
    result = await auth_client.put(DEFAULTS, json=choice())
    assert result.status_code == 200
    assert (await auth_client.get(DEFAULTS)).json()["settings"] == choice()
    assert (await auth_client.get(BASE)).json()["settings"] == previous
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "portrait-template")
        assert template.original_manifest[MANIFEST_KEY] == choice()


@pytest.mark.asyncio
async def test_invalid_update_does_not_replace_saved_style(auth_client, portrait_world):
    assert (await auth_client.put(BASE, json=choice())).status_code == 200
    invalid = choice()
    invalid["voice"]["instruction"] = "x" * 1501
    assert (await auth_client.put(BASE, json=invalid)).status_code == 422
    assert (await auth_client.get(BASE)).json()["settings"] == choice()


@pytest.mark.asyncio
async def test_foreign_sessions_and_templates_are_private(auth_client, portrait_world):
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "portrait-template")
        template.owner_id = None
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        session = await db.get(GameSession, "portrait-session")
        session.user_id = "other-owner"
        await db.commit()
    for url in (BASE, DEFAULTS):
        assert (await auth_client.get(url)).status_code == 404
        assert (await auth_client.put(url, json=choice())).status_code == 404


@pytest.mark.asyncio
async def test_export_import_and_new_session_snapshot_keep_style_and_world_brief(
    auth_client, portrait_world, monkeypatch
):
    from backend.engine.adventure_exporter import AdventureExporter
    from backend.engine.gameplay.world import AdventureLogic
    from backend.engine.import_restore_blueprint import restore_blueprint
    from backend.models.user import User

    monkeypatch.setattr(
        "backend.engine.media_engine.MediaEngine.generate_placeholder",
        AsyncMock(return_value="/data/placeholder.svg"),
    )
    monkeypatch.setattr("backend.engine.media_engine.MediaEngine.ensure_thumbnails", AsyncMock())
    assert (await auth_client.put(DEFAULTS, json=choice())).status_code == 200
    async with TestSessionLocal() as db:
        original = await db.get(AdventureTemplate, "portrait-template")
        original.original_manifest = {
            **original.original_manifest,
            "world_brief": {
                "setting": "An orbital city",
                "open_threads": "An unresolved treaty dispute",
            },
        }
        db.add(
            WorldScene(
                id="TOWER",
                template_id=original.id,
                label="Observatory",
                description="The talks begin.",
            )
        )
        await db.commit()
        manifest = await AdventureExporter.build_full_manifest(db, original.id)
        assert manifest[MANIFEST_KEY] == choice()
        assert manifest["world_brief"]["setting"] == "An orbital city"
        user = await db.get(User, original.owner_id)
        assert await restore_blueprint(db, manifest, user, user.id, None)
        await db.commit()
        imported = await db.scalar(
            select(AdventureTemplate).where(
                AdventureTemplate.id != original.id, AdventureTemplate.title == original.title
            )
        )
        snapshot = AdventureLogic.build_session_manifest_snapshot(imported)
        state = SimpleNamespace(entity_states={"__manifest_snapshot__": snapshot})
        assert read_settings(state).model_dump() == choice()
        assert (
            imported.original_manifest["world_brief"]["open_threads"]
            == "An unresolved treaty dispute"
        )
