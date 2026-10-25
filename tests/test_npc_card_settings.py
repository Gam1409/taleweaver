"""NPC card disclosure is explicit, session-owned, and survives world lifecycle operations."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import Text, cast, select, update

from backend.api.routes.adventures import adventure_creation, npc_card_settings
from backend.api.routes.adventures.adventure_creation import CoverSource, build_template
from backend.api.routes.adventures.generation_resume import _resume_job
from backend.api.routes.adventures.logic import AdventureLogic
from backend.api.routes.adventures.schemas import CreateAdventureTemplatePayload
from backend.core.adventure_format import CURRENT_VERSION
from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.adventure_importer import AdventureTemplateImporter
from backend.engine.manifest_apply.adventure_meta import apply_final_adventure_fields
from backend.engine.npc_cards.settings import (
    MANIFEST_KEY,
    SETTINGS_KEY,
    NpcCardSettings,
    card_insights_enabled,
)
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.engine.world_generator import WorldGenerator
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
SESSION = "portrait-session"
URL = f"/api/adventures/{SESSION}/npc-card-settings"
REAL_GENERATE_WORLD = WorldGenerator.generate_world


@pytest.mark.parametrize("enabled", [False, True])
def test_creation_and_generated_manifest_keep_author_choice(enabled):
    payload = CreateAdventureTemplatePayload(title="A reunion", show_npc_state=enabled)
    restored = CreateAdventureTemplatePayload.model_validate(payload.model_dump())
    template = build_template(restored, "world", "owner", CoverSource())
    assert template.original_manifest[MANIFEST_KEY] == {"show_state": enabled}
    generated = {"plot": "New content", MANIFEST_KEY: {"show_state": not enabled}}
    # Shared final application is used after both staged and monolithic generation.
    apply_final_adventure_fields(SimpleNamespace(adventure=template, manifest=generated))
    assert template.original_manifest[MANIFEST_KEY] == {"show_state": enabled}
    snapshot = AdventureLogic.build_session_manifest_snapshot(template)
    state = SimpleNamespace(entity_states={"__manifest_snapshot__": snapshot})
    assert card_insights_enabled(state) is enabled


@pytest.mark.parametrize("enabled", [False, True])
async def test_generator_first_manifest_write_preserves_explicit_preference(
    auth_client, monkeypatch, enabled
):
    manifest = {
        "plot": "A generated reunion",
        "scenes": [],
        "exits": [],
        "npcs": [],
        "objects": [],
        MANIFEST_KEY: {"show_state": not enabled},
    }
    generated = SimpleNamespace(
        model_dump=lambda: manifest, scenes=[], exits=[], npcs=[], objects=[]
    )
    llm = SimpleNamespace(provider="ollama", model="fake")
    monkeypatch.setattr(
        "backend.engine.world_generator.GameMasterLLM.for_role", lambda *a, **k: llm
    )
    monkeypatch.setattr(
        "backend.engine.staged_world.generate_manifest", AsyncMock(return_value=generated)
    )
    monkeypatch.setattr("backend.engine.world_manifest_applier.apply_manifest", AsyncMock())
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User))
        user.llm_settings = {"generator_model_provider": "ollama"}
        template = build_template(
            CreateAdventureTemplatePayload(title="Reunion", show_npc_state=enabled),
            "card-generation",
            user.id,
            CoverSource(),
        )
        db.add(template)
        await db.commit()
        await REAL_GENERATE_WORLD(
            db=db,
            user=user,
            template_id=template.id,
            title="Reunion",
            original_prompt="Friends meet",
        )
        assert template.original_manifest[MANIFEST_KEY] == {"show_state": enabled}
        assert template.original_manifest["plot"] == "A generated reunion"


@pytest.mark.parametrize("raw", [None, {}, "true", {"show_state": "true"}, {"show_state": 1}])
def test_old_or_malformed_settings_fail_closed(raw):
    snapshot = {"original_manifest": {MANIFEST_KEY: {"show_state": True}}}
    state = SimpleNamespace(entity_states={"__manifest_snapshot__": snapshot, SETTINGS_KEY: raw})
    assert card_insights_enabled(state) is False
    assert card_insights_enabled(SimpleNamespace(entity_states=raw)) is False
    assert card_insights_enabled(SimpleNamespace(entity_states={})) is False


async def test_owner_toggle_preserves_other_state_and_defaults_off(auth_client, portrait_world):
    assert (await auth_client.get(URL)).json() == {"show_state": False}
    response = await auth_client.patch(URL, json={"show_state": True})
    assert response.status_code == 200, response.text
    assert response.json() == {"show_state": True}
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SESSION))
        assert state.entity_states["NPC_NEW"]["hp"] == 17
        assert state.entity_states[SETTINGS_KEY] == {"show_state": True}
    assert (await auth_client.get(URL)).json() == {"show_state": True}
    assert (await auth_client.patch(URL, json={"show_state": False})).status_code == 200
    assert (await auth_client.get(URL)).json() == {"show_state": False}
    assert (await auth_client.patch(URL, json={"show_state": "true"})).status_code == 422
    assert (
        await auth_client.get("/api/adventures/other-session/npc-card-settings")
    ).status_code == 404
    denied = await auth_client.patch(
        "/api/adventures/other-session/npc-card-settings", json={"show_state": True}
    )
    assert denied.status_code == 404


async def test_toggle_rejects_turn_in_progress(auth_client, portrait_world):
    with session_write_lease(SESSION):
        response = await auth_client.patch(URL, json={"show_state": True})
    assert response.status_code == 409
    assert (await auth_client.get(URL)).json() == {"show_state": False}


@pytest.mark.parametrize("raw", [None, "invalid", []])
async def test_toggle_can_replace_legacy_invalid_json(auth_client, portrait_world, raw):
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SESSION))
        state.entity_states = raw
        await db.commit()
    assert (await auth_client.get(URL)).json() == {"show_state": False}
    response = await auth_client.patch(URL, json={"show_state": True})
    assert response.status_code == 200, response.text
    assert (await auth_client.get(URL)).json() == {"show_state": True}


async def test_compare_and_set_rejects_stale_json_without_losing_other_changes(
    auth_client, portrait_world
):
    async with TestSessionLocal() as db:
        state, before = (
            await db.execute(
                select(
                    SessionState, cast(SessionState.entity_states, Text).label("state_json")
                ).where(SessionState.session_id == SESSION)
            )
        ).one()
        concurrent = {**state.entity_states, "another-setting": {"value": "keep"}}
        await db.execute(
            update(SessionState)
            .where(SessionState.id == state.id)
            .values(entity_states=concurrent)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await npc_card_settings._save(db, state, before, NpcCardSettings(show_state=True))
        assert error.value.status_code == 409
        await db.refresh(state)
        assert state.entity_states == concurrent


async def test_template_snapshot_is_frozen_and_session_override_wins(auth_client, portrait_world):
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "portrait-template")
        template.original_manifest = {MANIFEST_KEY: {"show_state": True}}
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SESSION))
        state.entity_states = {
            **state.entity_states,
            "__manifest_snapshot__": AdventureLogic.build_session_manifest_snapshot(template),
        }
        await db.commit()
        template.original_manifest = {MANIFEST_KEY: {"show_state": False}}
        await db.commit()
    assert (await auth_client.get(URL)).json() == {"show_state": True}
    assert (await auth_client.patch(URL, json={"show_state": False})).status_code == 200
    assert (await auth_client.get(URL)).json() == {"show_state": False}


async def test_session_copy_and_ads_preserve_override(auth_client, portrait_world):
    assert (await auth_client.patch(URL, json={"show_state": True})).status_code == 200
    copied = await auth_client.post(f"/api/adventures/sessions/{SESSION}/copy")
    assert copied.status_code == 201, copied.text
    exported = await auth_client.get(f"/api/adventures/sessions/{SESSION}/export")
    assert exported.status_code == 200, exported.text
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("cards.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    for sid in (copied.json()["game_id"], imported.json()["game_id"]):
        assert (await auth_client.get(f"/api/adventures/{sid}/npc-card-settings")).json() == {
            "show_state": True
        }


async def test_template_copy_export_import_and_new_session_preserve_preference(
    auth_client, portrait_world
):
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "portrait-template")
        template.original_manifest = {
            "format_version": CURRENT_VERSION,
            MANIFEST_KEY: {"show_state": True},
        }
        template.rule_enforcement_mode = "vn"
        template.is_ready = True
        await db.commit()
        exported = await AdventureExporter.build_full_manifest(db, template.id)
        assert exported[MANIFEST_KEY] == {"show_state": True}
        exported["adventure"]["title"] = "Imported card settings"
        assert await AdventureTemplateImporter.import_adv_manifest(
            db, exported, owner_id=template.owner_id
        )
        imported = await db.scalar(
            select(AdventureTemplate).where(AdventureTemplate.title == "Imported card settings")
        )
        assert imported.original_manifest[MANIFEST_KEY] == {"show_state": True}
    copied = await auth_client.post("/api/adventures/portrait-template/copy")
    assert copied.status_code == 201, copied.text
    started = await auth_client.post(
        f"/api/adventures/{copied.json()['id']}/sessions/start", json={}
    )
    assert started.status_code == 201, started.text
    sid = started.json()["game_id"]
    assert (await auth_client.get(f"/api/adventures/{sid}/npc-card-settings")).json() == {
        "show_state": True
    }


async def test_failed_generation_resume_keeps_preference_outside_llm(auth_client, monkeypatch):
    monkeypatch.setattr(
        adventure_creation.WorldGenerator,
        "generate_world",
        AsyncMock(side_effect=RuntimeError("Simulated interrupted generation")),
    )
    response = await auth_client.post(
        "/api/adventures/", json={"title": "Saved card preference", "show_npc_state": True}
    )
    assert response.status_code == 201, response.text
    ids = response.json()
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, ids["adventure_id"])
        assert template.original_manifest[MANIFEST_KEY] == {"show_state": True}
        assert template.generation_request["payload"]["show_npc_state"] is True
        job = await _resume_job(db, template)
        assert job.payload.show_npc_state is True
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == ids["game_id"])
        )
        assert card_insights_enabled(state) is True
