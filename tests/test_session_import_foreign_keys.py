"""Legacy conversations round-trip with production SQLite FK enforcement."""

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.core.config import settings
from backend.engine.export_archives import pack_export_ads
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.models.avatar import Avatar
from backend.models.base import Base
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User


async def test_legacy_conversation_imports_with_foreign_keys_and_keeps_atomic_rollback(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "conversation.sqlite"))

    @event.listens_for(engine.sync_engine, "connect")
    def pragmas(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            user = User(username="conversation-owner", hashed_password="fictional-hash")
            db.add(user)
            await db.flush()
            avatar = Avatar(user_id=user.id, name="Visitor")
            db.add(avatar)
            await db.flush()
            game = GameSession(user_id=user.id, avatar_id=avatar.id)
            db.add(game)
            await db.flush()
            db.add(SessionState(session_id=game.id, user_id=user.id, avatar_id=avatar.id))
            db.add(
                ChatMessage(session_id=game.id, role="assistant", content="A fictional greeting.")
            )
            await db.commit()
            sid, owner = game.id, user.id
            manifest = await SessionExporter.build_session_manifest(db, sid)
            manifest.pop("world_info")  # Legacy ADS has no optional source corpus.
            wire = pack_export_ads(manifest, sid)
        async with sessions() as db:
            restored = await SessionImporter.import_ads(db, wire, owner)
            assert restored is not None
            reply = await db.scalar(select(ChatMessage).where(ChatMessage.session_id == restored))
            assert reply.content == "A fictional greeting."
            assert await db.scalar(select(func.count(GameSession.id))) == 2
            assert await db.scalar(select(func.count(Avatar.id))) == 2
        # Failure after parent rows flush must roll back the entire new save.
        invalid = {**manifest, "world_info": {"version": 99}}
        async with sessions() as db:
            assert (
                await SessionImporter.import_ads(db, pack_export_ads(invalid, sid), owner) is None
            )
            assert await db.scalar(select(func.count(GameSession.id))) == 2
            assert await db.scalar(select(func.count(Avatar.id))) == 2
            assert await db.scalar(select(func.count(ChatMessage.id))) == 2
    finally:
        await engine.dispose()
