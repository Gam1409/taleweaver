"""Both deployed migration paths can reach the combined feature head."""

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from alembic import command
from backend.core.config import settings


@pytest.mark.parametrize("parent", ["8f4c2a9d10be", "8f8c06e00a80"])
def test_upgrade_from_either_parent(tmp_path, monkeypatch, parent):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    assert ScriptDirectory.from_config(config).get_current_head() == "2d9b7a4c8e31"
    command.upgrade(config, parent)
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        schema = inspect(engine)
        assert "playtime_seconds" in {
            column["name"] for column in schema.get_columns("game_sessions")
        }
        assert "source_keys" in {
            column["name"] for column in schema.get_columns("memory_summaries")
        }
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version")) == "2d9b7a4c8e31"
            )
    finally:
        engine.dispose()
