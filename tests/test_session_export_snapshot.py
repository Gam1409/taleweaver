"""Complete ADS manifests keep canonical rows and references in one fresh snapshot."""

import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.core.config import settings
from backend.engine.export_archives import pack_export_ads
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.models.avatar import Avatar
from backend.models.base import Base
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemorySummary
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from backend.models.world_info import WorldInfoEntry
from backend.models.world_map import WorldMap
from tests.world_info_fixture import corpus, seed_corpus


@pytest_asyncio.fixture
async def snapshot_world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "snapshot.sqlite"))

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
            user = User(username="snapshot-owner", hashed_password="fictional-hash")
            db.add(user)
            await db.flush()
            avatar = Avatar(user_id=user.id, name="Archive visitor", hp=100)
            db.add(avatar)
            await db.flush()
            game = GameSession(
                user_id=user.id, avatar_id=avatar.id, adventure_title="Original archive"
            )
            db.add(game)
            await db.flush()
            db.add_all(
                [
                    SessionState(
                        session_id=game.id,
                        user_id=user.id,
                        avatar_id=avatar.id,
                        current_scene_id="ARCHIVE",
                        in_game_time=10,
                    ),
                    WorldScene(
                        session_id=game.id,
                        id="ARCHIVE",
                        label="Archive",
                        description="Original reading room.",
                    ),
                    WorldScene(
                        session_id=game.id, id="GARDEN", label="Garden", description="A garden."
                    ),
                    WorldExit(
                        session_id=game.id,
                        from_scene_id="ARCHIVE",
                        to_scene_id="GARDEN",
                        label="Original path",
                    ),
                    WorldEntity(
                        session_id=game.id,
                        id="EXISTING_GUIDE",
                        entity_type="NPC",
                        name="Existing guide",
                        description="Original guide description.",
                        current_scene_id="ARCHIVE",
                    ),
                    WorldMap(session_id=game.id, nodes={"label": "Original map"}, edges=[]),
                    ChatMessage(session_id=game.id, role="assistant", content="Original reply."),
                    MemorySummary(
                        session_id=game.id,
                        user_id=user.id,
                        layer="story_summary",
                        text="Original summary.",
                        source_hash="fictional-source-hash",
                        source_message_ids=[],
                    ),
                ]
            )
            payload = corpus()
            payload["entries"][1].update(audience="narrator_only", known_by=[])
            await seed_corpus(db, game.id, user.id, payload)
            await db.commit()
            yield sessions, game.id, user.id, payload
    finally:
        await engine.dispose()


async def test_concurrent_new_recipient_cannot_make_exported_save_unimportable(
    snapshot_world, monkeypatch
):
    sessions, sid, owner, payload = snapshot_world
    async with sessions() as reader:
        original = reader.execute
        interleaved = False

        async def interleave(statement, *args, **kwargs):
            nonlocal interleaved
            result = await original(statement, *args, **kwargs)
            if interleaved or "FROM world_entities" not in str(statement):
                return result
            interleaved = True
            async with sessions() as writer:
                writer.add(
                    WorldEntity(
                        session_id=sid,
                        id="NEW_GUIDE",
                        entity_type="NPC",
                        name="New guide",
                        description="A newly introduced guide.",
                        current_scene_id="ARCHIVE",
                    )
                )
                entry = await writer.get(WorldInfoEntry, payload["entries"][1]["id"])
                entry.audience, entry.known_by, entry.version = "restricted", ["NEW_GUIDE"], 2
                game = await writer.get(GameSession, sid)
                game.adventure_title = "Updated archive"
                avatar = await writer.get(Avatar, game.avatar_id)
                avatar.hp = 75
                state = await writer.scalar(
                    select(SessionState).where(SessionState.session_id == sid)
                )
                state.in_game_time = 20
                await writer.commit()
            return result

        monkeypatch.setattr(reader, "execute", interleave)
        manifest = await SessionExporter.build_session_manifest(reader, sid)
        assert interleaved
        wire = pack_export_ads(manifest, sid)
    async with sessions() as importer:
        restored = await SessionImporter.import_ads(importer, wire, owner)
        assert restored is not None
    assert manifest["game_session"]["adventure_title"] == "Original archive"
    assert manifest["avatar"]["hp"] == 100
    assert manifest["session_state"]["in_game_time"] == 10
    assert "NEW_GUIDE" not in {row["id"] for row in manifest["world_entities"]}
    assert manifest["world_info"]["entries"][1]["known_by"] == []
    async with sessions() as db:
        game = await db.get(GameSession, sid)
        assert game.adventure_title == "Updated archive"
        entry = await db.get(WorldInfoEntry, payload["entries"][1]["id"])
        assert entry.known_by == ["NEW_GUIDE"]


async def test_snapshot_refreshes_every_preloaded_manifest_identity(snapshot_world):
    sessions, sid, _, _ = snapshot_world
    models = (
        GameSession,
        SessionState,
        Avatar,
        ChatMessage,
        WorldEntity,
        WorldScene,
        WorldExit,
        WorldMap,
        MemorySummary,
    )
    async with sessions() as reader:
        # Keep strong references: an unexpired identity map must not bypass fresh SQL.
        preloaded = [list(await reader.scalars(select(model))) for model in models]
        async with sessions() as writer:
            game = await writer.get(GameSession, sid)
            game.adventure_title = "Fresh archive"
            avatar = await writer.get(Avatar, game.avatar_id)
            avatar.hp = 77
            state = await writer.scalar(select(SessionState))
            state.in_game_time = 33
            message = await writer.scalar(select(ChatMessage))
            message.content = "Fresh reply."
            npc = await writer.scalar(select(WorldEntity))
            npc.description = "Fresh guide description."
            scene = await writer.scalar(select(WorldScene).where(WorldScene.id == "ARCHIVE"))
            scene.description = "Fresh reading room."
            exit_row = await writer.scalar(select(WorldExit))
            exit_row.label = "Fresh path"
            world_map = await writer.scalar(select(WorldMap))
            world_map.nodes = {"label": "Fresh map"}
            summary = await writer.scalar(select(MemorySummary))
            summary.text = "Fresh summary."
            await writer.commit()
        manifest = await SessionExporter.build_session_manifest(reader, sid)
        assert manifest["game_session"]["adventure_title"] == "Fresh archive"
        assert manifest["avatar"]["hp"] == 77
        assert manifest["session_state"]["in_game_time"] == 33
        assert manifest["chat_messages"][0]["content"] == "Fresh reply."
        assert manifest["world_entities"][0]["description"] == "Fresh guide description."
        scene = next(row for row in manifest["world_scenes"] if row["id"] == "ARCHIVE")
        assert scene["description"] == "Fresh reading room."
        assert manifest["world_exits"][0]["label"] == "Fresh path"
        assert manifest["world_map"]["nodes"] == {"label": "Fresh map"}
        assert manifest["memory_summaries"][0]["text"] == "Fresh summary."
        assert len(preloaded) == len(models)
