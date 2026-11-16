"""Verify image receipts survive migration in both directions."""

import importlib.util
import json

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_image_details_roundtrip_without_losing_receipts():
    spec = importlib.util.spec_from_file_location(
        "image_receipts_migration",
        "alembic/versions/9ad17e20c002_archive_memory_and_image_details.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    receipt = {"image_url": "/data/example.png", "content_hash": "hash", "visual_trace": ["fact"]}
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE chat_messages (id TEXT PRIMARY KEY, session_id TEXT)"
        )
        connection.exec_driver_sql("CREATE TABLE memory_summaries (id TEXT PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE session_states (id TEXT PRIMARY KEY, session_id TEXT, entity_states JSON)"
        )
        connection.exec_driver_sql("INSERT INTO chat_messages VALUES ('message', 'session')")
        connection.exec_driver_sql(
            "INSERT INTO session_states VALUES ('state', 'session', ?)",
            (json.dumps({"__vn_illustrations__": {"images": {"message": receipt}}}),),
        )
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        stored = connection.exec_driver_sql("SELECT illustration FROM chat_messages").scalar_one()
        assert json.loads(stored) == receipt
        state = json.loads(
            connection.exec_driver_sql("SELECT entity_states FROM session_states").scalar_one()
        )
        assert "visual_trace" not in state["__vn_illustrations__"]["images"]["message"]
        module.downgrade()
        restored = json.loads(
            connection.exec_driver_sql("SELECT entity_states FROM session_states").scalar_one()
        )
        assert restored["__vn_illustrations__"]["images"]["message"] == receipt
    engine.dispose()
