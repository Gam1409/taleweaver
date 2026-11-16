"""Adventure Personality defaults must not overwrite already-started sessions."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.chpm.schema import Settings
from backend.engine.chpm.state import load
from backend.engine.chpm.template_settings import initial_states
from backend.engine.import_build_archive_template import build_archive_template
from backend.engine.import_build_blueprint_template import build_blueprint_template
from backend.engine.import_build_session_template import build_session_template
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import chpm_world, portrait_world

__all__ = ["chpm_world", "portrait_world"]
PATH = "/api/adventures/portrait-template"


async def test_new_sessions_copy_defaults_while_existing_minds_are_untouched(
    auth_client, chpm_world
):
    settings = Settings(mode="live", actor_ids=["NPC_NEW"]).model_dump(mode="json")
    response = await auth_client.patch(PATH, json={"npc_personality_settings": settings})
    assert response.status_code == 200, response.text
    assert response.json()["npc_personality_settings"] == settings
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "portrait-template")
        existing = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert load(existing).settings.mode == "off"
        assert (
            load(SimpleNamespace(entity_states=initial_states(template, {}))).settings.mode
            == "live"
        )
    started = await auth_client.post(PATH + "/sessions/start")
    assert started.status_code == 201, started.text
    new_id = started.json()["game_id"]
    settings["mode"] = "off"
    assert (
        await auth_client.patch(PATH, json={"npc_personality_settings": settings})
    ).status_code == 200
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == new_id))
        assert load(state).settings.mode == "live"
        assert load(state).minds == {} and load(state).recovery.total_simplified_turns == 0


@pytest.mark.parametrize("change", ["unknown_actor", "budget", "conflict"])
async def test_invalid_defaults_are_rejected_without_changing_template(
    auth_client, chpm_world, change
):
    settings = Settings(mode="live", actor_ids=["NPC_NEW"]).model_dump(mode="json")
    update = {"npc_personality_settings": settings}
    if change == "unknown_actor":
        settings["actor_ids"] = ["FOREIGN_NPC"]
    elif change == "budget":
        settings["max_calls_per_turn"] = 2
    else:
        update["living_world_settings"] = {
            "living_world_enabled": True,
            "deliberation_enabled": True,
        }
    response = await auth_client.patch(PATH, json=update)
    assert response.status_code == 422, response.text
    assert (await auth_client.get(PATH)).json()["npc_personality_settings"] is None


async def test_defaults_round_trip_in_each_adventure_bundle_without_private_minds(
    auth_client, chpm_world
):
    prefs = Settings(mode="live", actor_ids=["NPC_NEW"]).model_dump(mode="json")
    assert (
        await auth_client.patch(PATH, json={"npc_personality_settings": prefs})
    ).status_code == 200
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "portrait-template")
        manifest = await AdventureExporter.build_full_manifest(db, adventure.id)
        meta = manifest["adventure"]
        assert meta["npc_personality_settings"] == prefs
        copied = build_blueprint_template(
            manifest, manifest, meta, adventure.owner_id, None, "vn", False
        )
        archived = build_archive_template(
            "copy", adventure.owner_id, meta, manifest, None, "vn", False, None, None
        )
        session = build_session_template(
            {"adventure": meta}, SimpleNamespace(id=adventure.owner_id), None
        )
        for candidate in (copied, archived, session):
            assert candidate.npc_personality_settings == prefs
            fresh = load(
                SimpleNamespace(
                    entity_states=initial_states(candidate, {"unrelated": {"ok": True}})
                )
            )
            assert fresh.minds == {} and fresh.usage.calls == 0


def test_non_vn_defaults_remain_inactive_and_input_dictionary_is_not_mutated():
    states = {"existing": {"hp": 12}}
    adventure = SimpleNamespace(
        rule_enforcement_mode="rpg", npc_personality_settings=Settings().model_dump()
    )
    assert initial_states(adventure, states) == states


def test_additive_column_migration_preserves_rows_and_can_be_reversed():
    path = (
        Path(__file__).parents[1] / "alembic/versions/c8a2d4f6b801_add_npc_personality_defaults.py"
    )
    spec = importlib.util.spec_from_file_location("personality_defaults_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE adventure_templates (id TEXT PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO adventure_templates VALUES ('existing')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert (
                connection.execute(
                    sa.text("SELECT npc_personality_settings FROM adventure_templates")
                ).scalar()
                is None
            )
            migration.downgrade()
        assert (
            connection.execute(sa.text("SELECT id FROM adventure_templates")).scalar() == "existing"
        )
    engine.dispose()
