"""VN adventure defaults persist independently of existing live simulations."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.import_build_blueprint_template import build_blueprint_template
from backend.engine.living_world.schema import Settings
from backend.engine.living_world.template_settings import initial_state
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal


async def create(client, mode="vn"):
    prefs = Settings(
        living_world_enabled=True,
        deliberation_enabled=True,
        decision_engine="concordia",
        auto_schedule=True,
        max_decisions_per_run=3,
    )
    response = await client.post(
        "/api/adventures/",
        json={
            "title": "Concordia defaults",
            "avatar_name": "Hero",
            "rule_enforcement_mode": mode,
            "living_world_settings": prefs.model_dump(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json(), prefs.model_dump()


async def test_create_update_and_new_sessions_have_independent_defaults(auth_client):
    ids, prefs = await create(auth_client)
    tid = ids["adventure_id"]
    get = await auth_client.get(f"/api/adventures/{tid}")
    assert get.json()["living_world_settings"] == prefs
    async with TestSessionLocal() as db:
        first = await db.scalar(select(SessionState).where(SessionState.template_id == tid))
        first_id, first_timeline = first.session_id, first.living_world["timeline"]
        assert first.living_world["settings"] == prefs
    changed = {
        **prefs,
        "max_decisions_per_run": 1,
        "living_world_enabled": False,
        "deliberation_enabled": False,
    }
    response = await auth_client.patch(
        f"/api/adventures/{tid}", json={"living_world_settings": changed}
    )
    assert response.status_code == 200, response.text
    started = await auth_client.post(f"/api/adventures/{tid}/sessions/start")
    assert started.status_code == 201, started.text
    async with TestSessionLocal() as db:
        first = await db.scalar(select(SessionState).where(SessionState.session_id == first_id))
        second = await db.scalar(
            select(SessionState).where(SessionState.session_id == started.json()["game_id"])
        )
        assert first.living_world["settings"] == prefs
        assert second.living_world["settings"] == changed
        assert second.living_world["timeline"] != first_timeline
        assert second.living_world["events"] == []


async def test_non_vn_sessions_do_not_activate_stored_concordia_defaults(auth_client):
    ids, _ = await create(auth_client, "rpg")
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.template_id == ids["adventure_id"])
        )
        assert state.living_world is None


async def test_invalid_limits_and_unauthorized_template_are_rejected(auth_client):
    ids, prefs = await create(auth_client)
    response = await auth_client.patch(
        f"/api/adventures/{ids['adventure_id']}",
        json={
            "living_world_settings": {**prefs, "max_decisions_per_run": 500},
        },
    )
    assert response.status_code == 422
    assert (
        await auth_client.patch("/api/adventures/not-owned", json={"living_world_settings": prefs})
    ).status_code == 404
    capability = await auth_client.get("/api/adventures/living-world/capabilities")
    assert capability.status_code == 200 and "defaults" in capability.json()
    assert "api_key" not in capability.text


async def test_export_and_blueprint_import_keep_configuration_not_private_state(auth_client):
    ids, prefs = await create(auth_client)
    async with TestSessionLocal() as db:
        adv = await db.get(AdventureTemplate, ids["adventure_id"])
        exported = await AdventureExporter.build_full_manifest(db, adv.id)
        assert exported["adventure"]["living_world_settings"] == prefs
        restored = build_blueprint_template(
            exported, exported, exported["adventure"], adv.owner_id, None, "vn", False
        )
        assert restored.living_world_settings == prefs
        assert initial_state(restored)["private_notes"] == {}


def test_template_settings_migration_keeps_existing_rows_and_can_downgrade():
    path = (
        Path(__file__).parents[1]
        / "alembic/versions/b6d8f0a2c413_add_template_living_world_settings.py"
    )
    spec = importlib.util.spec_from_file_location("template_world_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE adventure_templates (id TEXT PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO adventure_templates VALUES ('existing')"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert (
                connection.execute(
                    sa.text("SELECT living_world_settings FROM adventure_templates")
                ).scalar()
                is None
            )
            module.downgrade()
        assert (
            connection.execute(sa.text("SELECT id FROM adventure_templates")).scalar() == "existing"
        )
    engine.dispose()
