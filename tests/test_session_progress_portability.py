"""Copies, archives and checkpoints preserve earned XP and chapter progress."""

import io
import json
import zipfile
from copy import deepcopy

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api.routes.adventures.sessions import copy_session
from backend.engine.gameplay.sequence_progress import evaluate_sequence_progress
from backend.engine.gameplay.world import AdventureLogic
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.engine.turn_replay.snapshot import capture, restore
from backend.models import (
    AdventureTemplate,
    Avatar,
    Base,
    GameSession,
    SessionState,
    User,
    WorldScene,
)

SEQUENCES = [
    {"id": "CH1", "title": "First chapter", "order": 10, "exp_reward": 10},
    {"id": "CH2", "title": "Second chapter", "order": 20, "exp_reward": 20},
    {"id": "CH3", "title": "Third chapter", "order": 30, "exp_reward": 30},
]


def _enable_foreign_keys(connection, _record):
    connection.execute("PRAGMA foreign_keys=ON")


@pytest_asyncio.fixture(params=["memory", "file"])
async def progress_db(request, tmp_path):
    location = ":memory:" if request.param == "memory" else str(tmp_path / "progress.sqlite")
    engine = create_async_engine(f"sqlite+aiosqlite:///{location}")
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        assert await db.scalar(text("PRAGMA foreign_keys")) == 1
        await _seed_progress(db)
        yield db
    await engine.dispose()


async def _seed_progress(db):
    db.add(User(id="owner", username="progress-owner", hashed_password="unused"))
    await db.flush()
    adventure = AdventureTemplate(
        id="template",
        owner_id="owner",
        title="Progress story",
        sequences=deepcopy(SEQUENCES),
        original_manifest={"sequences": deepcopy(SEQUENCES)},
    )
    db.add(adventure)
    await db.flush()
    db.add(Avatar(id="avatar", user_id="owner", template_id="template", name="Hero", exp=250))
    await db.flush()
    db.add(
        GameSession(
            id="source",
            user_id="owner",
            avatar_id="avatar",
            template_id="template",
            adventure_title="Progress story",
        )
    )
    await db.flush()
    db.add_all(
        [
            SessionState(
                session_id="source",
                user_id="owner",
                avatar_id="avatar",
                template_id="template",
                current_scene_id="ROOM",
                active_sequence_id="CH2",
                active_sequence_order=20,
                entity_states={
                    AdventureLogic.SESSION_MANIFEST_SNAPSHOT_KEY: AdventureLogic.build_session_manifest_snapshot(
                        adventure
                    )
                },
            ),
            WorldScene(id="ROOM", session_id="source", label="Room", description="A room."),
        ]
    )
    await db.commit()


async def _context(db, session_id="source"):
    game = await db.get(GameSession, session_id)
    state = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
    avatar = await db.get(Avatar, game.avatar_id)
    return game, state, avatar


async def _duplicate(db, operation):
    if operation == "copy":
        result = await copy_session("source", db, await db.get(User, "owner"))
        return result["game_id"]
    return await SessionImporter.import_ads(
        db, await SessionExporter.export_ads(db, "source"), "owner"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["copy", "ads"])
@pytest.mark.parametrize("earned_xp", [0, 250])
async def test_played_save_continues_the_same_chapter_and_xp(progress_db, operation, earned_xp):
    db = progress_db
    _, _, source_avatar = await _context(db)
    source_avatar.exp = earned_xp
    await db.commit()
    duplicated_id = await _duplicate(db, operation)
    assert duplicated_id is not None
    _, state, avatar = await _context(db, duplicated_id)
    assert (state.active_sequence_id, state.active_sequence_order, avatar.exp) == (
        "CH2",
        20,
        earned_xp,
    )
    adventure = await db.get(AdventureTemplate, "template")
    messages = evaluate_sequence_progress(adventure, state, avatar, force_complete=True)
    assert messages == [
        "Sequence completed: Second chapter (+20 XP)",
        "New Sequence unlocked: Third chapter",
    ]
    await db.commit()
    db.expunge_all()
    _, state, avatar = await _context(db, duplicated_id)
    assert (state.active_sequence_id, state.active_sequence_order, avatar.exp) == (
        "CH3",
        30,
        earned_xp + 20,
    )
    _, original_state, original_avatar = await _context(db)
    assert (
        original_state.active_sequence_id,
        original_state.active_sequence_order,
        original_avatar.exp,
    ) == ("CH2", 20, earned_xp)
    roundtrip_id = await SessionImporter.import_ads(
        db, await SessionExporter.export_ads(db, duplicated_id), "owner"
    )
    assert roundtrip_id is not None
    _, state, avatar = await _context(db, roundtrip_id)
    assert (state.active_sequence_id, state.active_sequence_order, avatar.exp) == (
        "CH3",
        30,
        earned_xp + 20,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["copy", "ads"])
async def test_fresh_progress_defaults_remain_unchanged(progress_db, operation):
    db = progress_db
    _, state, avatar = await _context(db)
    state.active_sequence_id, state.active_sequence_order, avatar.exp = None, 1, 0
    await db.commit()
    duplicated_id = await _duplicate(db, operation)
    assert duplicated_id is not None
    _, state, avatar = await _context(db, duplicated_id)
    assert (state.active_sequence_id, state.active_sequence_order, avatar.exp) == (None, 1, 0)


@pytest.mark.asyncio
async def test_legacy_ads_without_progress_fields_uses_legacy_defaults(progress_db):
    db = progress_db
    original = await SessionExporter.export_ads(db, "source")
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as archive, zipfile.ZipFile(buffer, "w") as legacy:
        manifest = json.loads(archive.read("session.json"))
        manifest["session_state"].pop("active_sequence_id")
        manifest["session_state"].pop("active_sequence_order")
        manifest["avatar"].pop("exp")
        for name in archive.namelist():
            content = (
                json.dumps(manifest).encode() if name == "session.json" else archive.read(name)
            )
            legacy.writestr(name, content)
    session_id = await SessionImporter.import_ads(db, buffer.getvalue(), "owner")
    assert session_id is not None
    _, state, avatar = await _context(db, session_id)
    assert (state.active_sequence_id, state.active_sequence_order, avatar.exp) == (None, 1, 0)


async def _checkpoint(db):
    saved = await SessionCheckpointService.create_checkpoint(db, "source", "MANUAL")
    await db.commit()
    return saved


async def _advance_to_future(db):
    game, state, avatar = await _context(db)
    state.active_sequence_id, state.active_sequence_order, avatar.exp = "CH3", 30, 900
    state.is_completed, game.status = True, "completed"
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("active_id,order", [(None, 1), ("CH1", 10), ("CH2", 20)])
async def test_checkpoint_rewinds_chapter_pair_and_xp(progress_db, active_id, order):
    db = progress_db
    _, state, _ = await _context(db)
    state.active_sequence_id, state.active_sequence_order = active_id, order
    saved = await _checkpoint(db)
    assert saved.state_snapshot["session_state"].get("active_sequence_order") == order
    await _advance_to_future(db)
    await SessionCheckpointService.restore_checkpoint(db, "source", saved.id)
    await db.commit()
    db.expunge_all()
    game, state, avatar = await _context(db)
    assert (state.active_sequence_id, state.active_sequence_order, avatar.exp) == (
        active_id,
        order,
        250,
    )
    assert state.is_completed is False and game.status == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "definitions",
    ["snapshot", "template", "absent", "start", "unknown", "canonical-edited", "canonical-empty"],
)
async def test_legacy_checkpoint_missing_order_resolves_saved_chapter(progress_db, definitions):
    db = progress_db
    _, state, _ = await _context(db)
    saved_id = None if definitions == "start" else "UNKNOWN" if definitions == "unknown" else "CH2"
    state.active_sequence_id = saved_id
    saved = await _checkpoint(db)
    snapshot = deepcopy(saved.state_snapshot)
    snapshot["session_state"].pop("active_sequence_order", None)
    if definitions in {"template", "absent"}:
        snapshot["session_state"]["entity_states"] = {}
    if definitions in {"canonical-edited", "canonical-empty"}:
        saved_adventure = snapshot["session_state"]["entity_states"][
            AdventureLogic.SESSION_MANIFEST_SNAPSHOT_KEY
        ]["adventure"]
        saved_adventure["sequences"] = (
            [{"id": "CH2", "order": 25}] if definitions == "canonical-edited" else []
        )
    saved.state_snapshot = snapshot
    template = await db.get(AdventureTemplate, "template")
    if definitions == "snapshot":
        template.sequences = [{"id": "CH2", "order": 200}]
    if definitions == "absent":
        template.sequences = []
    await db.commit()
    await _advance_to_future(db)
    await SessionCheckpointService.restore_checkpoint(db, "source", saved.id)
    await db.commit()
    db.expunge_all()
    _, state, avatar = await _context(db)
    expected_order = {"snapshot": 20, "template": 20, "canonical-edited": 25}.get(definitions, 1)
    assert (state.active_sequence_id, state.active_sequence_order, avatar.exp) == (
        saved_id,
        expected_order,
        250,
    )


@pytest.mark.asyncio
async def test_legacy_checkpoint_without_chapter_fields_retains_current_pair(progress_db):
    db = progress_db
    saved = await _checkpoint(db)
    snapshot = deepcopy(saved.state_snapshot)
    snapshot["session_state"].pop("active_sequence_id")
    snapshot["session_state"].pop("active_sequence_order", None)
    saved.state_snapshot = snapshot
    await db.commit()
    await _advance_to_future(db)
    await SessionCheckpointService.restore_checkpoint(db, "source", saved.id)
    await db.commit()
    db.expunge_all()
    _, state, avatar = await _context(db)
    assert (state.active_sequence_id, state.active_sequence_order, avatar.exp) == ("CH3", 30, 250)


@pytest.mark.asyncio
async def test_full_turn_replay_already_restores_progress_and_xp(progress_db):
    db = progress_db
    snapshot = await capture(db, "source")
    await _advance_to_future(db)
    await restore(db, "source", snapshot)
    await db.commit()
    _, state, avatar = await _context(db)
    assert (state.active_sequence_id, state.active_sequence_order, avatar.exp) == ("CH2", 20, 250)
