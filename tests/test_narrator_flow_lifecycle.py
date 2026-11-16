"""Additive narrator preferences retain the existing settings and save boundaries."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from backend.api.routes.adventures import story_authoring
from backend.engine.narrator.settings import (
    MANIFEST_KEY,
    SETTINGS_KEY,
    manifest_settings,
    preserve_settings,
    read_settings,
)
from backend.engine.turn_replay.snapshot import capture, restore
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_narrator_settings import BASE, DEFAULTS, choice, portrait_world
from tests.test_session_authored_fields import TEMPLATE, seed_template
from tests.test_vn_turn_integration import seed_vn

__all__ = ["portrait_world"]


def selected(flow, *, verbosity="rich"):
    return {**choice(), "flow": flow, "verbosity": verbosity}


@pytest.mark.parametrize("location", ["manifest", "override"])
def test_legacy_voice_and_verbosity_gain_only_the_default_flow(location):
    legacy = choice()
    legacy.pop("flow")
    original = deepcopy(legacy)
    frozen = {"__manifest_snapshot__": {"original_manifest": {MANIFEST_KEY: legacy}}}
    if location == "override":
        frozen = {
            **frozen,
            SETTINGS_KEY: legacy,
            "__manifest_snapshot__": {"original_manifest": {MANIFEST_KEY: selected("off")}},
        }
    restored = read_settings(SimpleNamespace(entity_states=frozen)).model_dump()
    assert restored == {**legacy, "flow": "gentle"}
    assert restored["voice"] == original["voice"]
    assert restored["verbosity"] == original["verbosity"]
    assert legacy == original and "flow" not in legacy


@pytest.mark.parametrize("flow", ["off", "gentle", "balanced"])
def test_author_defaults_survive_generation_with_existing_voice_and_verbosity(flow):
    authored = {MANIFEST_KEY: selected(flow), "world_brief": {"setting": "Coastal archive"}}
    original = deepcopy(authored)
    generated = preserve_settings(
        {MANIFEST_KEY: {"flow": "off", "voice": None, "verbosity": "terse"}},
        SimpleNamespace(original_manifest=authored),
    )
    assert generated[MANIFEST_KEY] == authored[MANIFEST_KEY]
    assert manifest_settings(generated).model_dump() == selected(flow)
    assert authored == original


@pytest.mark.asyncio
@pytest.mark.parametrize("flow", ["off", "gentle", "balanced"])
async def test_session_flow_enum_roundtrips_and_legacy_put_is_additive(
    auth_client, portrait_world, flow
):
    payload = selected(flow, verbosity="dialogue")
    assert (await auth_client.put(BASE, json=payload)).status_code == 200
    assert (await auth_client.get(BASE)).json()["settings"] == payload
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.entity_states[SETTINGS_KEY] == payload
        assert state.entity_states["NPC_NEW"]["hp"] == 17
    legacy = deepcopy(payload)
    legacy.pop("flow")
    assert (await auth_client.put(BASE, json=legacy)).status_code == 200
    assert (await auth_client.get(BASE)).json()["settings"] == {**legacy, "flow": flow}


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [BASE, DEFAULTS])
@pytest.mark.parametrize("flow", ["off", "balanced"])
async def test_legacy_update_preserves_selected_flow_and_replaces_existing_fields(
    auth_client, portrait_world, url, flow
):
    assert (await auth_client.put(url, json=selected(flow))).status_code == 200
    legacy = {"voice": None, "verbosity": "terse"}
    expected = {**legacy, "flow": flow}
    response = await auth_client.put(url, json=legacy)
    assert response.status_code == 200
    assert response.json()["settings"] == expected
    assert (await auth_client.get(url)).json()["settings"] == expected
    # Existing PUT replacement behavior for the older fields remains unchanged.
    assert (await auth_client.put(url, json={})).json()["settings"] == {
        "voice": None,
        "verbosity": "default",
        "flow": flow,
    }
    explicit = selected("gentle", verbosity="dialogue")
    assert (await auth_client.put(url, json=explicit)).json()["settings"] == explicit


@pytest.mark.asyncio
@pytest.mark.parametrize("flow", ["off", "balanced"])
async def test_legacy_session_update_preserves_effective_frozen_flow_without_override(
    auth_client, portrait_world, flow
):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {
            **state.entity_states,
            "__manifest_snapshot__": {"original_manifest": {MANIFEST_KEY: selected(flow)}},
        }
        assert SETTINGS_KEY not in state.entity_states
        await db.commit()
    assert (await auth_client.get(BASE)).json()["settings"]["flow"] == flow
    legacy = {"voice": None, "verbosity": "terse"}
    response = await auth_client.put(BASE, json=legacy)
    assert response.status_code == 200
    assert response.json()["settings"] == {**legacy, "flow": flow}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_flow", ["unknown", "balanced ", None, False, [], {}])
async def test_invalid_flow_preserves_previous_session_and_author_defaults(
    auth_client, portrait_world, bad_flow
):
    before = selected("balanced", verbosity="epic")
    invalid = {**selected("off", verbosity="terse"), "flow": bad_flow}
    for url in [BASE, DEFAULTS]:
        assert (await auth_client.put(url, json=before)).status_code == 200
        assert (await auth_client.put(url, json=invalid)).status_code == 422
        assert (await auth_client.get(url)).json()["settings"] == before


@pytest.mark.asyncio
async def test_busy_session_and_generating_template_preserve_settings(auth_client, portrait_world):
    before = selected("balanced")
    assert (await auth_client.put(BASE, json=before)).status_code == 200
    assert (await auth_client.put(DEFAULTS, json=before)).status_code == 200
    with session_write_lease("portrait-session"):
        assert (await auth_client.put(BASE, json=selected("off"))).status_code == 409
        assert (
            await auth_client.put(BASE, json={"voice": None, "verbosity": "terse"})
        ).status_code == 409
    assert (await auth_client.get(BASE)).json()["settings"] == before
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "portrait-template")
        template.generation_run_id = "current-generation"
        template.creation_status = "Generating..."
        template.is_ready = False
        await db.commit()
    assert (await auth_client.put(DEFAULTS, json=selected("off"))).status_code == 409
    assert (
        await auth_client.put(DEFAULTS, json={"voice": None, "verbosity": "terse"})
    ).status_code == 409
    assert (await auth_client.get(DEFAULTS)).json()["settings"] == before


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [BASE, DEFAULTS])
@pytest.mark.parametrize("legacy", [False, True])
async def test_compare_and_swap_rejects_raced_json_without_discarding_other_state(
    auth_client, portrait_world, monkeypatch, url, legacy
):
    previous = selected("balanced")
    assert (await auth_client.put(url, json=previous)).status_code == 200
    original_commit = story_authoring._commit
    model, key, identifier = (
        (SessionState, SETTINGS_KEY, "portrait-session")
        if url == BASE
        else (AdventureTemplate, MANIFEST_KEY, "portrait-template")
    )
    column = model.entity_states if url == BASE else model.original_manifest
    predicate = model.session_id == identifier if url == BASE else model.id == identifier

    async def commit_after_another_writer(db, statement):
        current = dict(await db.scalar(select(column).where(predicate)))
        current["parallel_revision"] = {"sequence": 2}
        await db.execute(update(model).where(predicate).values({column.key: current}))
        await db.commit()
        await original_commit(db, statement)

    monkeypatch.setattr(story_authoring, "_commit", commit_after_another_writer)
    attempted = selected("off", verbosity="terse")
    if legacy:
        attempted.pop("flow")
    response = await auth_client.put(url, json=attempted)
    assert response.status_code == 409, response.text
    assert (await auth_client.get(url)).json()["settings"] == previous
    async with TestSessionLocal() as db:
        stored = await db.scalar(select(column).where(predicate))
        assert stored[key] == previous
        assert stored["parallel_revision"] == {"sequence": 2}


@pytest.mark.asyncio
async def test_flow_settings_keep_owner_authorization(auth_client, portrait_world):
    before = (await auth_client.get(BASE)).json()["settings"]
    foreign = "/api/adventures/other-session/narrator-settings"
    assert (await auth_client.get(foreign)).status_code == 404
    assert (await auth_client.put(foreign, json=selected("balanced"))).status_code == 404
    assert (await auth_client.get(BASE)).json()["settings"] == before
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "portrait-template")
        template.owner_id = None
        await db.commit()
    assert (await auth_client.put(DEFAULTS, json=selected("off"))).status_code == 404


@pytest.mark.asyncio
async def test_new_session_frozen_defaults_override_and_save_archive_remain_distinct(
    auth_client, monkeypatch, tmp_path
):
    await seed_template(monkeypatch, tmp_path, "vn", "template")
    defaults = f"/api/adventures/{TEMPLATE}/narrator-defaults"
    author = selected("balanced")
    assert (await auth_client.put(defaults, json=author)).status_code == 200
    started = await auth_client.post(f"/api/adventures/{TEMPLATE}/sessions/start")
    assert started.status_code == 201, started.text
    session_id = started.json()["game_id"]
    session_url = f"/api/adventures/{session_id}/narrator-settings"
    assert (await auth_client.get(session_url)).json()["settings"] == author
    revised = selected("off", verbosity="terse")
    assert (await auth_client.put(defaults, json=revised)).status_code == 200
    assert (await auth_client.get(session_url)).json()["settings"] == author
    newer = await auth_client.post(f"/api/adventures/{TEMPLATE}/sessions/start")
    assert newer.status_code == 201, newer.text
    assert (
        await auth_client.get(f"/api/adventures/{newer.json()['game_id']}/narrator-settings")
    ).json()["settings"] == revised
    override = {"voice": None, "verbosity": "dialogue", "flow": "gentle"}
    assert (await auth_client.put(session_url, json=override)).status_code == 200
    copied = await auth_client.post(f"/api/adventures/sessions/{session_id}/copy")
    assert copied.status_code == 201, copied.text
    copy_id = copied.json()["game_id"]
    exported = await auth_client.get(f"/api/adventures/sessions/{copy_id}/export")
    assert exported.status_code == 200, exported.text
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("narrator.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    for identifier in [session_id, copy_id, imported.json()["game_id"]]:
        assert (await auth_client.get(f"/api/adventures/{identifier}/narrator-settings")).json()[
            "settings"
        ] == override
        async with TestSessionLocal() as db:
            state = await db.scalar(
                select(SessionState).where(SessionState.session_id == identifier)
            )
            assert state.entity_states[SETTINGS_KEY] == override
            assert (
                state.entity_states["__manifest_snapshot__"]["original_manifest"][MANIFEST_KEY]
                == author
            )
    assert (await auth_client.get(defaults)).json()["settings"] == revised


@pytest.mark.asyncio
async def test_pre_turn_snapshot_restores_flow_voice_and_verbosity_together():
    async with TestSessionLocal() as db:
        _, _, state, _ = await seed_vn(db)
        before = selected("balanced", verbosity="dialogue")
        state.entity_states = {
            **state.entity_states,
            SETTINGS_KEY: before,
            "saved_marker": "before",
        }
        await db.commit()
        snapshot = await capture(db, state.session_id)
        state.entity_states = {
            **state.entity_states,
            SETTINGS_KEY: selected("off", verbosity="terse"),
            "saved_marker": "after",
        }
        await db.commit()
        await restore(db, "session-1", snapshot)
        await db.commit()
        restored = await db.scalar(
            select(SessionState).where(SessionState.session_id == "session-1")
        )
        assert read_settings(restored).model_dump() == before
        assert restored.entity_states[SETTINGS_KEY] == before
        assert restored.entity_states["saved_marker"] == "before"
