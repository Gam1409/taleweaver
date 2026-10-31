"""Simulation persistence shares existing snapshot/export boundaries."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from backend.engine.living_world.schema import Event
from backend.engine.living_world.state import load, save
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.engine.session_exporter import SessionExporter
from tests.conftest import TestSessionLocal
from tests.test_living_world import demo, seed


def test_migration_preserves_old_rows_and_downgrades_without_simulation_columns():
    path = Path(__file__).parents[1] / "alembic/versions/9a0c4e7b1d62_add_living_world_state.py"
    spec = importlib.util.spec_from_file_location("living_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE session_states (id TEXT PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE game_sessions (id TEXT PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO session_states (id) VALUES ('old')"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert (
                connection.execute(
                    sa.text("SELECT living_world FROM session_states WHERE id='old'")
                ).scalar()
                is None
            )
            module.downgrade()
        assert [
            column["name"] for column in sa.inspect(connection).get_columns("session_states")
        ] == ["id"]
        assert connection.execute(sa.text("SELECT id FROM session_states")).scalar() == "old"
    engine.dispose()


async def test_checkpoint_rewinds_private_queue_and_forks_timeline():
    async with TestSessionLocal() as db:
        _, state = await seed(db)
        sim = demo()
        save(state, sim)
        await db.commit()
        checkpoint = await SessionCheckpointService.create_checkpoint(db, "session-1", "MANUAL")
        await db.commit()
        sim.events.append(
            Event(event_id="future-secret", due=200, kind="DECISION", actor="MIRINDA")
        )
        save(state, sim)
        state.entity_states = {"LILI": {"current_scene_id": "ROOM"}}
        await db.commit()
        await SessionCheckpointService.restore_checkpoint(db, "session-1", checkpoint.id)
        await db.commit()
        await db.refresh(state)
        restored = load(state)
        assert restored.timeline != sim.timeline
        assert "future-secret" not in {event.event_id for event in restored.events}
        assert len(restored.events) == 3
        assert state.entity_states.get("LILI", {}).get("current_scene_id", "START") == "START"


async def test_export_keeps_simulation_with_its_session_not_in_public_entity_metadata():
    async with TestSessionLocal() as db:
        _, state = await seed(db)
        sim = demo()
        save(state, sim)
        await db.commit()
        exported = await SessionExporter.build_session_manifest(db, "session-1")
        assert exported["session_state"]["living_world"]["timeline"] == sim.timeline
        assert len(exported["session_state"]["living_world"]["events"]) == 3
        assert all(
            "living_world" not in (entity.get("metadata_json") or {})
            for entity in exported["world_entities"]
        )
