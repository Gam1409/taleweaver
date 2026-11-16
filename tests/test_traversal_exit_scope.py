"""Traversal resolves the current stored passage before checking locks or hooks."""

import pytest
from sqlalchemy import select

from backend.models import AdventureTemplate, SessionState, WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.traversal_exit_support import passage, seed_traversal_world, traverse

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("reference", ["START::END", " start :: end ", "template_id", "session_id"])
@pytest.mark.parametrize("template_locked", [False, True])
async def test_actual_traversal_obeys_each_sessions_lock_and_stored_hooks(
    monkeypatch, reference, template_locked
):
    async with TestSessionLocal() as db:
        world = await seed_traversal_world(
            db, template_locked=template_locked, current_locked=not template_locked
        )
        for session_id in ("one", "two"):
            row = world.exits[session_id]
            exit_ref = (
                world.template_exit.id.upper()
                if reference == "template_id"
                else row.id.upper()
                if reference == "session_id"
                else reference
            )
            chunks = await traverse(world, session_id, exit_ref, monkeypatch)
            moved = not row.is_locked
            assert any("event: scene_transition" in chunk for chunk in chunks) is moved
            assert world.states[session_id].current_scene_id == ("END" if moved else "START")
            variables = (world.states[session_id].entity_states or {}).get("__script_vars__", {})
            assert variables.get("passage_source") == (session_id if moved else None)
            assert variables.get("opened_source") == (session_id if moved else None)
        async with TestSessionLocal() as reader:
            for session_id in ("one", "two"):
                state = await reader.scalar(
                    select(SessionState).where(SessionState.session_id == session_id)
                )
                assert state.current_scene_id == (
                    "START" if world.exits[session_id].is_locked else "END"
                )
            original = await reader.get(WorldExit, world.template_exit.id)
            assert original.is_locked is template_locked


@pytest.mark.parametrize("reference", ["END::START", "template_id", "session_id"])
@pytest.mark.parametrize("session_type", ["bidirectional", "one_way"])
async def test_reverse_traversal_uses_session_direction_even_if_template_is_bidirectional(
    monkeypatch, reference, session_type
):
    async with TestSessionLocal() as db:
        world = await seed_traversal_world(db, template_locked=False, current_type=session_type)
        world.states["one"].current_scene_id = "END"
        await db.commit()
        exit_ref = (
            world.template_exit.id
            if reference == "template_id"
            else world.exits["one"].id
            if reference == "session_id"
            else reference
        )
        chunks = await traverse(world, "one", exit_ref, monkeypatch)
        allowed = session_type == "bidirectional"
        assert any("event: scene_transition" in chunk for chunk in chunks) is allowed
        assert world.states["one"].current_scene_id == ("START" if allowed else "END")
        assert world.exits["one"].from_scene_id == "START"
        assert world.exits["one"].to_scene_id == "END"
        variables = (world.states["one"].entity_states or {}).get("__script_vars__", {})
        assert variables.get("passage_source") == ("one" if allowed else None)


async def test_session_bidirectional_reverse_works_when_template_is_one_way(monkeypatch):
    async with TestSessionLocal() as db:
        world = await seed_traversal_world(db, template_type="one_way")
        world.states["one"].current_scene_id = "END"
        await db.commit()
        chunks = await traverse(world, "one", "END::START", monkeypatch)
        assert any("event: scene_transition" in chunk for chunk in chunks)
        assert world.states["one"].current_scene_id == "START"


async def test_foreign_session_and_foreign_template_ids_never_resolve(monkeypatch):
    async with TestSessionLocal() as db:
        world = await seed_traversal_world(db)
        db.add(
            AdventureTemplate(id="foreign-template", owner_id=world.user.id, title="Other study")
        )
        await db.flush()
        foreign = passage(
            id="foreign-template-exit", template_id="foreign-template", is_locked=False
        )
        db.add(foreign)
        await db.commit()
        for reference in (world.exits["two"].id, foreign.id):
            chunks = await traverse(world, "one", reference, monkeypatch)
            assert any("not found" in chunk for chunk in chunks)
            assert world.states["one"].current_scene_id == "START"


@pytest.mark.parametrize("reference", ["START::END", "template_id"])
async def test_template_fallback_still_works_for_a_legacy_session_without_counterpart(
    monkeypatch, reference
):
    async with TestSessionLocal() as db:
        world = await seed_traversal_world(db, template_locked=False)
        await db.delete(world.exits["one"])
        await db.commit()
        exit_ref = world.template_exit.id if reference == "template_id" else reference
        chunks = await traverse(world, "one", exit_ref, monkeypatch)
        assert any("event: scene_transition" in chunk for chunk in chunks)
        assert world.states["one"].entity_states["__script_vars__"]["passage_source"] == "template"


@pytest.mark.parametrize("reference", ["START::END", "orphan_id"])
async def test_detached_session_never_uses_an_unscoped_orphan_as_template_fallback(
    monkeypatch, reference
):
    async with TestSessionLocal() as db:
        world = await seed_traversal_world(db)
        world.states["one"].template_id = None
        await db.delete(world.exits["one"])
        orphan = passage(id="orphan-exit", is_locked=False, exit_type="bidirectional")
        db.add(orphan)
        await db.commit()
        chunks = await traverse(
            world, "one", orphan.id if reference == "orphan_id" else reference, monkeypatch
        )
        assert not any("event: scene_transition" in chunk for chunk in chunks)
        assert world.states["one"].current_scene_id == "START"


async def test_actual_session_traversal_uses_session_scene_hooks_and_target_label(monkeypatch):
    async with TestSessionLocal() as db:
        world = await seed_traversal_world(db, template_locked=False)
        rows = (await db.scalars(select(WorldScene))).all()
        for row in rows:
            marker = row.session_id or "template"
            if row.id == "START":
                row.on_leave_scene_script = f"tw.vars.set('left_source', '{marker}')"
            else:
                row.label = f"Destination {marker}"
                row.on_enter_scene_script = f"tw.vars.set('entered_source', '{marker}')"
        await db.commit()
        chunks = await traverse(world, "one", world.exits["one"].id, monkeypatch)
        assert world.states["one"].entity_states["__script_vars__"]["left_source"] == "one"
        assert world.states["one"].entity_states["__script_vars__"]["entered_source"] == "one"
        assert any('"scene_label": "Destination one"' in chunk for chunk in chunks)
        async with TestSessionLocal() as reader:
            saved = await reader.scalar(
                select(SessionState).where(SessionState.session_id == "one")
            )
            assert saved.entity_states["__script_vars__"]["left_source"] == "one"


async def test_source_deletion_keeps_two_detached_session_passages_isolated(monkeypatch):
    from backend.engine.gameplay.world import AdventureLogic
    from backend.models import Avatar

    async with TestSessionLocal() as db:
        orphan = passage(id="old-unscoped-exit", is_locked=False, exit_type="bidirectional")
        db.add(orphan)
        await db.flush()
        world = await seed_traversal_world(db)
        await AdventureLogic.delete_adventure(db, world.template.id)
        db.expunge_all()
        for session_id in ("one", "two"):
            state = await db.scalar(
                select(SessionState).where(SessionState.session_id == session_id)
            )
            assert state.template_id is None
            world.states[session_id] = state
            world.avatars[session_id] = await db.get(Avatar, state.avatar_id)
            chunks = await traverse(world, session_id, "START::END", monkeypatch)
            assert any("event: scene_transition" in chunk for chunk in chunks) is (
                session_id == "one"
            )
            assert state.current_scene_id == ("END" if session_id == "one" else "START")


@pytest.mark.parametrize(
    "template_type,session_type",
    [
        ("bidirectional", "bidirectional"),
        ("bidirectional", "one_way"),
        ("one_way", "bidirectional"),
    ],
)
@pytest.mark.parametrize("template_locked", [False, True])
@pytest.mark.parametrize("origin", ["START", "END"])
@pytest.mark.parametrize("reference", ["composite", "template_id", "session_id"])
async def test_reversed_counterpart_obeys_session_rules_for_all_reference_forms(
    monkeypatch, template_type, session_type, template_locked, origin, reference
):
    async with TestSessionLocal() as db:
        world = await seed_traversal_world(
            db,
            template_locked=template_locked,
            current_locked=not template_locked,
            template_type=template_type,
            current_type=session_type,
        )
        row = world.exits["one"]
        row.from_scene_id, row.to_scene_id = "END", "START"
        world.states["one"].current_scene_id = origin
        await db.commit()
        destination = "END" if origin == "START" else "START"
        exit_ref = (
            world.template_exit.id
            if reference == "template_id"
            else row.id
            if reference == "session_id"
            else f"{origin}::{destination}"
        )
        chunks = await traverse(world, "one", exit_ref, monkeypatch)
        allowed = not row.is_locked and (origin == "END" or session_type == "bidirectional")
        assert any("event: scene_transition" in chunk for chunk in chunks) is allowed
        assert world.states["one"].current_scene_id == (destination if allowed else origin)
        variables = (world.states["one"].entity_states or {}).get("__script_vars__", {})
        assert variables.get("passage_source") == ("one" if allowed else None)


async def test_opposite_one_way_exits_remain_separate_passages(monkeypatch):
    async with TestSessionLocal() as db:
        world = await seed_traversal_world(
            db,
            template_locked=False,
            current_locked=True,
            template_type="one_way",
            current_type="one_way",
        )
        world.exits["one"].from_scene_id, world.exits["one"].to_scene_id = "END", "START"
        await db.commit()
        chunks = await traverse(world, "one", world.template_exit.id, monkeypatch)
        assert any("event: scene_transition" in chunk for chunk in chunks)
        assert world.states["one"].current_scene_id == "END"
        assert world.states["one"].entity_states["__script_vars__"]["passage_source"] == "template"
        chunks = await traverse(world, "one", "END::START", monkeypatch)
        assert not any("event: scene_transition" in chunk for chunk in chunks)
        assert world.states["one"].current_scene_id == "END"


async def test_ordered_counterpart_has_priority_over_reverse_bidirectional_passage(monkeypatch):
    async with TestSessionLocal() as db:
        world = await seed_traversal_world(db, template_locked=False, current_locked=True)
        reverse = passage(
            id="another-reverse-exit", session_id="one", is_locked=False, exit_type="bidirectional"
        )
        reverse.from_scene_id, reverse.to_scene_id = "END", "START"
        db.add(reverse)
        await db.commit()
        chunks = await traverse(world, "one", world.template_exit.id, monkeypatch)
        assert not any("event: scene_transition" in chunk for chunk in chunks)
        assert world.states["one"].current_scene_id == "START"


async def test_ambiguous_reverse_counterparts_cannot_fall_back_to_open_template(monkeypatch):
    async with TestSessionLocal() as db:
        world = await seed_traversal_world(db, template_locked=False, current_locked=False)
        world.exits["one"].from_scene_id, world.exits["one"].to_scene_id = "END", "START"
        reverse = passage(
            id="another-reverse-exit", session_id="one", is_locked=True, exit_type="bidirectional"
        )
        reverse.from_scene_id, reverse.to_scene_id = "END", "START"
        db.add(reverse)
        await db.commit()
        chunks = await traverse(world, "one", world.template_exit.id, monkeypatch)
        assert not any("event: scene_transition" in chunk for chunk in chunks)
        assert world.states["one"].current_scene_id == "START"
        assert "passage_source" not in (world.states["one"].entity_states or {}).get(
            "__script_vars__", {}
        )
        chunks = await traverse(world, "one", world.exits["one"].id, monkeypatch)
        assert any("event: scene_transition" in chunk for chunk in chunks)
        assert world.states["one"].entity_states["__script_vars__"]["passage_source"] == "one"
