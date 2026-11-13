"""Portable exports read cursors and their rows from the same SQL snapshot."""

from sqlalchemy import delete, event, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.engine.world_info.portability import export_world_info
from backend.models.avatar import Avatar
from backend.models.base import Base
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision
from tests.world_info_fixture import seed_corpus


async def test_export_is_consistent_when_another_writer_changes_entries_between_table_reads(
    tmp_path, monkeypatch
):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "export-snapshot.sqlite"))

    @event.listens_for(engine.sync_engine, "connect")
    def pragmas(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            user = User(username="snapshot-owner", hashed_password="fictional-password-hash")
            db.add(user)
            await db.flush()
            avatar = Avatar(user_id=user.id, name="Harbor keeper")
            db.add(avatar)
            await db.flush()
            game = GameSession(user_id=user.id, avatar_id=avatar.id)
            db.add(game)
            await db.flush()
            db.add(
                WorldEntity(
                    id="NPC_NEW",
                    session_id=game.id,
                    entity_type="NPC",
                    name="Guide",
                    description="A fictional guide.",
                    current_scene_id="TOWER",
                )
            )
            payload = await seed_corpus(db, game.id, user.id)
            await db.commit()
            session_id, owner = game.id, user.id
        async with sessions() as reader:
            original = reader.scalars
            interleaved = False

            async def interleave(statement, *args, **kwargs):
                nonlocal interleaved
                rows = await original(statement, *args, **kwargs)
                tables = {getattr(table, "name", None) for table in statement.get_final_froms()}
                if interleaved or "world_info_revisions" not in tables:
                    return rows
                interleaved = True
                async with sessions() as writer:
                    await writer.execute(
                        delete(WorldInfoEntry).where(
                            WorldInfoEntry.id == payload["entries"][0]["id"]
                        )
                    )
                    await writer.execute(
                        update(WorldInfoRevision)
                        .where(WorldInfoRevision.id == payload["revisions"][0]["id"])
                        .values(entries_count=1, facts_count=1)
                    )
                    await writer.commit()
                return rows

            monkeypatch.setattr(reader, "scalars", interleave)
            exported = await export_world_info(reader, session_id, owner)
            assert interleaved
            assert len(exported["entries"]) == 2
            first = next(row for row in exported["revisions"] if row["number"] == 1)
            assert first["entries_count"] == first["facts_count"] == 2
        async with sessions() as db:
            assert len(list(await db.scalars(select(WorldInfoEntry)))) == 1
    finally:
        await engine.dispose()
