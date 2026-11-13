"""Scene/exit rules and session ownership survive world lifecycle operations."""

import io
import json
import zipfile
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import event, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api.routes.adventures.session_copy_world import clone_saved_world
from backend.api.routes.adventures.session_materializer import _copy_world_to_session
from backend.api.routes.adventures.session_start_world import clone_template_world
from backend.api.routes.adventures.template_reset import rebuild_template_world
from backend.engine.adventure_cloner import _clone_exits, _clone_scenes
from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.gameplay.unlock_service import enforce_exit_guard, open_exit
from backend.engine.gameplay.world import AdventureLogic
from backend.engine.manifest_apply.context import ApplyContext
from backend.engine.manifest_apply.scenes import persist_exits, persist_scenes
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.engine.trigger_service import TriggerService
from backend.engine.world_location_fields import exit_fields, scene_fields
from backend.models import (
    AdventureTemplate,
    Avatar,
    Base,
    GameSession,
    SessionState,
    User,
    WorldEntity,
    WorldExit,
    WorldMap,
    WorldScene,
)

SCENE_HOOKS = {
    "on_enter_scene_script": "tw.vars.set('entered', True)",
    "on_enter_scene_text": "Entry notice",
    "on_leave_scene_script": "tw.vars.set('left', True)",
    "on_leave_scene_text": "Departure notice",
}
EXIT_RULES = {
    "unlock_expression": "tw.vars.get('permitted') == True",
    "on_open_exit_script": "tw.vars.set('opened', True)",
    "on_open_exit_text": "Opening notice",
    "on_exit_used_script": "tw.vars.set('used', True)",
    "on_exit_used_text": "Passage notice",
    "on_unlock_success_script": "tw.vars.set('unlocked', True)",
    "on_unlock_success_text": "Unlocked notice",
    "on_unlock_failure_script": "tw.vars.set('blocked', True)",
    "on_unlock_failure_text": "Blocked notice",
}
WORLD_MODELS = (WorldScene, WorldExit, WorldEntity, WorldMap)


def _enable_foreign_keys(connection, _record):
    connection.execute("PRAGMA foreign_keys=ON")


@pytest_asyncio.fixture(params=["memory", "file"])
async def world_db(request, tmp_path):
    location = ":memory:" if request.param == "memory" else str(tmp_path / "world.sqlite")
    engine = create_async_engine(f"sqlite+aiosqlite:///{location}")
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        assert await db.scalar(text("PRAGMA foreign_keys")) == 1
        await _seed_world(db)
        yield db
    await engine.dispose()


async def _seed_world(db):
    db.add(User(id="owner", username="world-owner", hashed_password="unused"))
    await db.flush()
    db.add(
        AdventureTemplate(
            id="template",
            owner_id="owner",
            title="Portable world",
            original_manifest={
                "scenes": [{"id": "ROOM", "name": "Reset room", **SCENE_HOOKS}],
                "objects": [{"id": "TOKEN", "name": "Reset token", "start_scene_id": "ROOM"}],
            },
        )
    )
    await db.flush()
    db.add(Avatar(id="avatar", user_id="owner", template_id="template", name="Hero"))
    await db.flush()
    for session_id in ("source", "target"):
        db.add(
            GameSession(id=session_id, user_id="owner", avatar_id="avatar", template_id="template")
        )
    await db.flush()
    for session_id in ("source", "target"):
        db.add(
            SessionState(
                session_id=session_id,
                user_id="owner",
                avatar_id="avatar",
                template_id="template",
                current_scene_id="ROOM",
            )
        )
    for scope in ({"template_id": "template"}, {"session_id": "source"}):
        db.add_all(
            [
                WorldScene(
                    id="ROOM",
                    label="Room",
                    description="A quiet room.",
                    decorative_objects=["shelf"],
                    **SCENE_HOOKS,
                    **scope,
                ),
                WorldExit(
                    from_scene_id="ROOM",
                    to_scene_id="NEXT",
                    label="Door",
                    exit_type="bidirectional",
                    is_locked=True,
                    lock_description="A closed door",
                    code_to_unlock="1234",
                    item_to_unlock="KEY",
                    rule_to_unlock="Find permission",
                    **EXIT_RULES,
                    **scope,
                ),
                WorldEntity(
                    id="TOKEN",
                    entity_type="OBJECT",
                    name="Token",
                    description="A token.",
                    current_scene_id="ROOM",
                    **scope,
                ),
                WorldMap(nodes={"ROOM": {"visited": True}}, edges=[], **scope),
            ]
        )
    await db.commit()


async def _session_row(db, model, session_id):
    return await db.scalar(select(model).where(model.session_id == session_id))


async def _clone_world(db, operation):
    if operation == "import":
        archive = await SessionExporter.export_ads(db, "source")
        session_id = await SessionImporter.import_ads(db, archive, "owner")
        assert session_id is not None
        return session_id
    session = await db.get(GameSession, "target")
    if operation == "start":
        avatar = await db.get(Avatar, "avatar")
        await clone_template_world(db, "template", session, avatar, {}, {})
    elif operation == "materialize":
        await _copy_world_to_session(db, "template", "target", {})
    else:
        source = await db.get(GameSession, "source")
        await clone_saved_world(db, source, session, {}, {})
    await db.commit()
    return "target"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["start", "materialize", "copy", "import"])
async def test_world_lifecycle_preserves_and_executes_scene_exit_rules(world_db, operation):
    db = world_db
    session_id = await _clone_world(db, operation)
    scene = await _session_row(db, WorldScene, session_id)
    exit_row = await _session_row(db, WorldExit, session_id)
    assert {key: getattr(scene, key) for key in SCENE_HOOKS} == SCENE_HOOKS
    assert {key: getattr(exit_row, key) for key in EXIT_RULES} == EXIT_RULES
    assert scene.decorative_objects == ["shelf"]
    assert exit_row.exit_type == "bidirectional"
    assert exit_row.code_to_unlock == "1234"
    assert exit_row.item_to_unlock == "KEY"
    assert exit_row.rule_to_unlock == "Find permission"
    await _assert_executable_rules(db, session_id, scene, exit_row)


async def _assert_executable_rules(db, session_id, scene, exit_row):
    state = await _session_row(db, SessionState, session_id)
    with pytest.raises(HTTPException) as blocked:
        await enforce_exit_guard(db, state, exit_row)
    assert blocked.value.status_code == 403
    assert blocked.value.detail == EXIT_RULES["on_unlock_failure_text"]
    assert state.entity_states["__script_vars__"]["blocked"] is True
    state.entity_states = {"__script_vars__": {"permitted": True}}
    await enforce_exit_guard(db, state, exit_row)
    await open_exit(db, state, exit_row, "The door unlocks.")
    for target, trigger in (
        (scene, "on_enter_scene"),
        (scene, "on_leave_scene"),
        (exit_row, "on_open_exit"),
        (exit_row, "on_exit_used"),
    ):
        messages = await TriggerService.execute_trigger(
            db,
            state,
            trigger,
            target.id,
            script_code=getattr(target, f"{trigger}_script"),
            narrative_text=getattr(target, f"{trigger}_text"),
        )
        assert getattr(target, f"{trigger}_text") in messages
    assert state.entity_states["__script_vars__"] == {
        "permitted": True,
        "unlocked": True,
        "entered": True,
        "left": True,
        "opened": True,
        "used": True,
    }


@pytest.mark.asyncio
async def test_imported_world_is_owned_only_by_the_session(world_db):
    session_id = await _clone_world(world_db, "import")
    for model in WORLD_MODELS:
        row = await _session_row(world_db, model, session_id)
        assert row is not None
        assert row.template_id is None
    game = await world_db.get(GameSession, session_id)
    assert game.template_id == "template"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["delete", "reset"])
@pytest.mark.parametrize("legacy_ownership", [False, True])
async def test_template_lifecycle_preserves_imported_session_world(
    world_db, operation, legacy_ownership
):
    db = world_db
    session_id = await _clone_world(db, "import")
    if legacy_ownership:
        await _set_legacy_ownership(db, session_id)
    await db.commit()
    before = await SessionExporter.build_session_manifest(db, session_id)
    db.expunge_all()
    if operation == "delete":
        await AdventureLogic.delete_adventure(db, "template")
    else:
        await rebuild_template_world(db, await db.get(AdventureTemplate, "template"))
        await db.commit()
    db.expunge_all()
    for model in WORLD_MODELS:
        row = await _session_row(db, model, session_id)
        assert row is not None, f"{model.__name__} lost during {operation}"
        assert row.template_id is None
    after = await SessionExporter.build_session_manifest(db, session_id)
    _assert_same_world(before, after)
    await _assert_template_content(db, operation)
    game = await db.get(GameSession, session_id)
    state = await _session_row(db, SessionState, session_id)
    avatar = await db.get(Avatar, game.avatar_id)
    expected_template = None if operation == "delete" else "template"
    assert (game.template_id, state.template_id, avatar.template_id) == (expected_template,) * 3
    scene = await _session_row(db, WorldScene, session_id)
    exit_row = await _session_row(db, WorldExit, session_id)
    restored_id = await SessionImporter.import_ads(
        db, await SessionExporter.export_ads(db, session_id), "owner"
    )
    assert restored_id is not None
    restored = await SessionExporter.build_session_manifest(db, restored_id)
    _assert_same_world(after, restored)
    await _assert_executable_rules(db, session_id, scene, exit_row)


async def _set_legacy_ownership(db, session_id):
    for model in WORLD_MODELS:
        await db.execute(
            update(model).where(model.session_id == session_id).values(template_id="template")
        )


def _assert_same_world(before, after):
    system_keys = {"pk", "template_id", "session_id", "created_at", "updated_at"}
    for section in ("world_scenes", "world_exits", "world_entities", "world_map"):
        omitted = system_keys | ({"id"} if section in {"world_exits", "world_map"} else set())
        left = before[section] if isinstance(before[section], list) else [before[section]]
        right = after[section] if isinstance(after[section], list) else [after[section]]
        assert [{k: v for k, v in row.items() if k not in omitted} for row in left] == [
            {k: v for k, v in row.items() if k not in omitted} for row in right
        ]


async def _assert_template_content(db, operation):
    if operation == "delete":
        assert await db.get(AdventureTemplate, "template") is None
        for model in WORLD_MODELS:
            assert await db.scalar(select(model).where(model.template_id == "template")) is None
        return
    scene = await db.scalar(select(WorldScene).where(WorldScene.template_id == "template"))
    entity = await db.scalar(select(WorldEntity).where(WorldEntity.template_id == "template"))
    assert scene.label == "Reset room"
    assert entity.name == "Reset token"
    assert {key: getattr(scene, key) for key in SCENE_HOOKS} == SCENE_HOOKS


@pytest.mark.asyncio
async def test_legacy_archive_without_scene_exit_rules_keeps_defaults(world_db):
    source = await SessionExporter.export_ads(world_db, "source")
    archive = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as original, zipfile.ZipFile(archive, "w") as legacy:
        manifest = json.loads(original.read("session.json"))
        _omit_fields(manifest["world_scenes"], SCENE_HOOKS)
        _omit_fields(manifest["world_exits"], (*EXIT_RULES, "exit_type", "is_locked"))
        for name in original.namelist():
            content = (
                json.dumps(manifest).encode() if name == "session.json" else original.read(name)
            )
            legacy.writestr(name, content)
    session_id = await SessionImporter.import_ads(world_db, archive.getvalue(), "owner")
    assert session_id is not None
    scene = await _session_row(world_db, WorldScene, session_id)
    exit_row = await _session_row(world_db, WorldExit, session_id)
    assert all(getattr(scene, key) is None for key in SCENE_HOOKS)
    assert all(getattr(exit_row, key) is None for key in EXIT_RULES)
    assert exit_row.exit_type == "one_way"
    assert exit_row.is_locked is False
    state = await _session_row(world_db, SessionState, session_id)
    await enforce_exit_guard(world_db, state, exit_row)


def _omit_fields(rows, fields):
    for row in rows:
        for key in fields:
            row.pop(key, None)


@pytest.mark.asyncio
async def test_template_clone_export_and_manifest_apply_share_rules(world_db, monkeypatch):
    db = world_db
    db.add_all(
        AdventureTemplate(id=template_id, owner_id="owner", title=template_id)
        for template_id in ("duplicate", "restored")
    )
    await db.flush()
    await _clone_scenes(db, "template", "duplicate")
    await _clone_exits(db, "template", "duplicate")
    manifest = await AdventureExporter.build_full_manifest(db, "duplicate")
    monkeypatch.setattr(
        "backend.engine.manifest_apply.scenes._scene_image", AsyncMock(return_value=None)
    )
    context = ApplyContext(
        db=db, template_id="restored", manifest=manifest, user=None, adventure=None
    )
    await persist_scenes(context, manifest["scenes"])
    persist_exits(db, "restored", manifest["exits"])
    await _copy_world_to_session(db, "restored", "target", {})
    await db.commit()
    scene = await _session_row(db, WorldScene, "target")
    exit_row = await _session_row(db, WorldExit, "target")
    assert {key: getattr(scene, key) for key in SCENE_HOOKS} == SCENE_HOOKS
    assert {key: getattr(exit_row, key) for key in EXIT_RULES} == EXIT_RULES
    await _assert_executable_rules(db, "target", scene, exit_row)


@pytest.mark.parametrize("model,mapper", [(WorldScene, scene_fields), (WorldExit, exit_fields)])
def test_portable_location_fields_cover_all_non_system_columns(model, mapper):
    system_keys = {"pk", "template_id", "session_id", "created_at", "updated_at"}
    if model is WorldExit:
        system_keys.add("id")
    assert set(mapper({})) == set(model.__table__.columns.keys()) - system_keys
