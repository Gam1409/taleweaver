"""The additive summary migration preserves legacy text and evidence hashes."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_fragment_migration_roundtrip_preserves_existing_summaries():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/8f4c2a9d10be_add_summary_fragment_coverage.py"
    )
    spec = importlib.util.spec_from_file_location("fragment_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE memory_summaries (id TEXT PRIMARY KEY, text TEXT, source_hash TEXT)"
                )
            )
            connection.execute(
                text("INSERT INTO memory_summaries VALUES ('old', 'A previous summary', 'hash')")
            )
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade()
                assert "source_keys" in {
                    col["name"] for col in inspect(connection).get_columns("memory_summaries")
                }
                assert connection.execute(
                    text("SELECT text, source_hash, source_keys FROM memory_summaries")
                ).one() == ("A previous summary", "hash", None)
                module.downgrade()
                assert connection.execute(
                    text("SELECT text, source_hash FROM memory_summaries")
                ).one() == ("A previous summary", "hash")
    finally:
        engine.dispose()
