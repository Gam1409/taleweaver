"""Upgrade existing databases and enforce World Info ownership trees in SQLite."""

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, delete, inspect, select, text
from sqlalchemy.orm import Session

from alembic import command
from backend.core.config import settings
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource
from tests.world_info_fixture import corpus

TABLES = ("world_info_sources", "world_info_revisions", "world_info_entries")


@pytest.mark.parametrize("parent", ["source", "session"])
def test_upgrade_cascade_and_downgrade_preserve_existing_user_data(tmp_path, monkeypatch, parent):
    monkeypatch.setattr(
        settings, "DATABASE_URL", "sqlite:///" + str(tmp_path / "world-info.sqlite")
    )
    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    command.upgrade(config, "d9b3e5a7c904")
    engine = create_engine(settings.DATABASE_URL)
    with Session(engine) as db:
        db.execute(text("PRAGMA foreign_keys=ON"))
        user = User(username="migration-owner", hashed_password="fictional-password-hash")
        db.add(user)
        db.flush()
        avatar = Avatar(user_id=user.id, name="Harbor keeper")
        db.add(avatar)
        db.flush()
        game = GameSession(user_id=user.id, avatar_id=avatar.id)
        db.add(game)
        db.commit()
        owner_id, session_id = user.id, game.id
    command.upgrade(config, "head")
    command.check(config)
    schema = inspect(engine)
    assert set(TABLES) <= set(schema.get_table_names())
    assert any(
        set(unique["column_names"]) == {"source_id", "number"}
        for unique in schema.get_unique_constraints("world_info_revisions")
    )
    assert any(
        set(unique["column_names"]) == {"source_revision_id", "batch_index", "ordinal"}
        for unique in schema.get_unique_constraints("world_info_entries")
    )
    for table in TABLES:
        foreign = schema.get_foreign_keys(table)
        assert all(row["referred_table"] != "adventure_templates" for row in foreign)
        assert all(row["options"]["ondelete"] == "CASCADE" for row in foreign)
    payload = corpus()
    with Session(engine) as db:
        db.execute(text("PRAGMA foreign_keys=ON"))
        for key, model in (
            ("sources", WorldInfoSource),
            ("revisions", WorldInfoRevision),
            ("entries", WorldInfoEntry),
        ):
            db.add_all(
                model(**row, session_id=session_id, user_id=owner_id) for row in payload[key]
            )
            db.flush()
        if parent == "source":
            db.execute(
                delete(WorldInfoSource).where(WorldInfoSource.id == payload["sources"][0]["id"])
            )
        else:
            db.execute(delete(GameSession).where(GameSession.id == session_id))
        db.commit()
        for model in (WorldInfoSource, WorldInfoRevision, WorldInfoEntry):
            assert db.scalar(select(model.id)) is None
        assert db.get(User, owner_id).username == "migration-owner"
    command.downgrade(config, "d9b3e5a7c904")
    assert not set(TABLES) & set(inspect(engine).get_table_names())
    with Session(engine) as db:
        assert db.get(User, owner_id).username == "migration-owner"
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()
