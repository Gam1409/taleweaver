"""Reliability contracts: bounded deferral, evidence provenance and atomic hook retry."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.living_world.runner import run
from backend.engine.living_world.schema import Event, Settings, Simulation
from backend.engine.scene_illustrations import fidelity, render
from backend.engine.scene_staging import props
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_living_world import seed


def test_props_require_placement_and_retract_with_their_revision():
    state = SimpleNamespace(current_scene_id="hall", entity_states={})
    items = [{"item_id": "BOOK", "owner_id": "HERO", "name": "Book"}]
    text = "Hero puts the Book on the desk."
    props.reconcile(
        state, text, [props.PropDelta(item_id="BOOK", owner_id="HERO", evidence=text)], items
    )
    assert props.project(state, items) == []  # Provisional is not an image fact.
    props.reconcile(
        state,
        text,
        [
            props.PropDelta(
                item_id="BOOK",
                owner_id="HERO",
                evidence=text,
                spatial_position="on the desk",
                status="confirmed",
            )
        ],
        items,
    )
    message = SimpleNamespace(id="m1", revision_id="r1", content=text)
    props.stamp(state, message)
    assert props.project(state, items)[0]["spatial_position"] == "on the desk"
    assert state.entity_states[props.KEY]["items"][0]["source_revision_id"] == "r1"
    assert props.project(state, []) == []  # No longer owned / now equipped.
    props.retract(state, "m1")
    assert props.project(state, items) == []


def test_unknown_or_unquoted_prop_cannot_become_visible():
    state = SimpleNamespace(current_scene_id="hall", entity_states={})
    items = [{"item_id": "BOOK", "owner_id": "HERO", "name": "Book"}]
    props.reconcile(
        state,
        "Hero waits.",
        [
            props.PropDelta(
                item_id="BOOK",
                owner_id="HERO",
                evidence="Hero waits.",
                spatial_position="on the desk",
                status="confirmed",
            )
        ],
        items,
    )
    assert props.project(state, items) == []


async def test_adapter_retries_missing_anchor_once_then_fails_visibly(monkeypatch):
    adapted = AsyncMock(return_value="A painted landscape.")
    monkeypatch.setattr(render, "adapt_body", adapted)
    request = {
        "prompt": "frozen source",
        "provider": "openai",
        "provider_options": {"_prompt_user": object()},
        "_scene_facts": {"characters": [{"id": "H", "name": "Hero"}]},
    }
    with pytest.raises(ValueError, match="No image was submitted"):
        await render.prepare_moment_prompt(request)
    assert adapted.await_count == 2
    assert "Missing literal anchor" in adapted.call_args.args[0]
    assert not request["provider_options"].get("_prompt_prepared")


def test_fidelity_checks_count_visible_clothing_and_prop_placement():
    facts = {
        "characters": [{"name": "Hero", "clothing_tokens": ["Blue coat"]}],
        "props": [{"name": "Book", "spatial_position": "on the desk"}],
    }
    assert fidelity.literal_diff("1 people. Hero in a Blue coat; Book on the desk.", facts) == []
    assert "on the desk" in fidelity.literal_diff("1 people. Hero in Blue coat with Book.", facts)


async def test_background_move_defers_once_per_window_and_eventually_reports_attempt(setup_test_db):
    async with TestSessionLocal() as db:
        _, state = await seed(db)
        db.add(
            ChatMessage(
                session_id=state.session_id,
                scene_id="START",
                role="assistant",
                content="The conversation continues.",
                created_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        simulation = Simulation(
            settings=Settings(living_world_enabled=True, mode="CATCH_UP"),
            target=30,
            events=[Event(event_id="move", due=1, kind="MOVE", actor="NPC", destination="ROOM")],
        )
        # Use the seeded movable NPC's identifier.
        from sqlalchemy import select

        from backend.models.world_entity import WorldEntity

        actor = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.entity_type == "NPC"
            )
        )
        simulation.events[0].actor = actor.id
        for count in range(1, 4):
            simulation.events[0].retry_after = 0
            await run(db, state, simulation)
            event = simulation.events[0]
            assert event.deferrals == count
            assert event.status == ("CANCELLED" if count == 3 else "DEFERRED")
        assert "abandoned" in event.result
        assert event.observed_by_player


async def test_hook_retry_rolls_back_effects_and_completed_boundary_is_not_replayed(setup_test_db):
    from backend.engine.hook_ledger import run as run_hook
    from backend.models.hook_run import HookRun
    from tests.test_combat_triggers import _seed

    async with TestSessionLocal() as db:
        _, avatar, state = await _seed(db)
        manager = SimpleNamespace(
            db=db, state=state, avatar=avatar, game_id=state.session_id, _hook_boundary="test-turn"
        )
        calls = 0
        original_hp = avatar.hp

        async def callback():
            nonlocal calls
            calls += 1
            avatar.hp -= 10
            if calls == 1:
                raise TimeoutError("temporary")
            return ["done"]

        assert await run_hook(manager, "test", callback) == ["done"]
        assert avatar.hp == original_hp - 10
        assert await run_hook(manager, "test", callback) == []
        assert calls == 2
        ledger = await db.get(HookRun, (state.session_id, "test-turn", "test"))
        assert ledger.status == "completed" and ledger.attempts == 2


async def test_checkpoint_retention_keeps_pinned_and_manual_and_restores_status(setup_test_db):
    from sqlalchemy import select

    from backend.engine.session_checkpoint_service import SessionCheckpointService
    from backend.models.game_session import GameSession
    from backend.models.session_checkpoint import SessionCheckpoint
    from tests.test_combat_triggers import _seed

    async with TestSessionLocal() as db:
        user, _, state = await _seed(db)
        session = GameSession(
            id=state.session_id,
            user_id=user.id,
            avatar_id=state.avatar_id,
            template_id=state.template_id,
            status="active",
        )
        db.add(session)
        await db.commit()
        manual = await SessionCheckpointService.create_checkpoint(db, state.session_id, "MANUAL")
        pinned = await SessionCheckpointService.create_checkpoint(
            db, state.session_id, "SCENE_CHANGE"
        )
        pinned.state_snapshot = {**pinned.state_snapshot, "pinned": True}
        for _ in range(7):
            await SessionCheckpointService.create_checkpoint(db, state.session_id, "SCENE_CHANGE")
        await db.commit()
        checkpoints = (await db.scalars(select(SessionCheckpoint))).all()
        assert len(checkpoints) == 7
        assert manual in checkpoints and pinned in checkpoints
        session.status = "completed"
        state.is_completed = True
        await db.commit()
        await SessionCheckpointService.restore_checkpoint(db, state.session_id, manual.id)
        assert session.status == "active" and not state.is_completed


def test_note_overflow_is_archived_without_changing_active_budget():
    from backend.api.routes.adventures.turn_helpers import TurnSessionStateHelper
    from backend.models.session_state import SessionState

    state = SessionState(exit_states={})
    helper = TurnSessionStateHelper(
        SimpleNamespace(state=state),
        gm_notes_state_key="notes",
        gm_notes_max_items=20,
        terminal_epilogue_state_key="terminal",
    )
    helper.apply_gm_notes_update([f"Fact {index}" for index in range(22)], None, False)
    assert helper.get_gm_notes() == [f"Fact {index}" for index in range(2, 22)]
    assert state.exit_states["notes_archive"] == ["Fact 0", "Fact 1"]
