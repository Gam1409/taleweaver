import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.chpm.schema import Settings
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.visual_novel import player_item_check as checks
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.turn_replay import TurnReplay
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_prose_evidence import event
from tests.test_vn_turn_integration import seed_vn

PLAYER = checks.PLAYER


def test_legacy_settings_stay_permissive_and_keep_original_wire_shape():
    assert "reject_impossible_player_items" not in Settings().model_dump()
    for raw in (
        None,
        {},
        {"schema_version": 0},
        {"settings": {"reject_impossible_player_items": False}},
    ):
        assert not checks.enabled(SimpleNamespace(entity_states={"__chpm__": raw}))
    assert checks.enabled(
        SimpleNamespace(
            entity_states={"__chpm__": {"settings": {"reject_impossible_player_items": True}}}
        )
    )


def fact(kind, value, **extra):
    return {
        "kind": kind,
        "value": value,
        "performer_id": PLAYER,
        "actor_id": PLAYER,
        "resolved": True,
        "item_id": "COAT",
        "recipient_id": "RIN",
        **extra,
    }


def test_chronological_simulation_keeps_owner_and_wardrobe_data_intact():
    owners = {"COAT": checks.SCENE}
    worn = {PLAYER: set()}
    sequence = [
        fact("custody", "picked_up"),
        fact("clothing", "worn"),
        fact("clothing", "partially_removed"),
        fact("clothing", "removed"),
        fact("custody", "given"),
    ]
    assert checks.contradiction(sequence, owners, worn, {}) is None
    assert owners == {"COAT": checks.SCENE} and worn == {PLAYER: set()}
    rejected = checks.contradiction(sequence + [fact("custody", "placed")], owners, worn, {})
    assert rejected and rejected[0] == "You do not have this item in your inventory."


def test_require_known_wearer_and_order_before_refusing():
    remove = fact("clothing", "removed", actor_id="RIN")
    assert checks.contradiction([remove], {}, {}, {"RIN": "Rin"}) is None
    rejected = checks.contradiction([remove], {}, {"RIN": set()}, {"RIN": "Rin"})
    assert rejected and rejected[0] == "Rin is not wearing this item."
    assert not checks._ordered_item_events(
        [dict(remove, start=0, end=25), dict(remove, start=10, end=17)]
    )
    assert not checks._ordered_item_events([dict(remove, performer_id=None, start=0, end=2)])


@pytest.mark.asyncio
@pytest.mark.parametrize(("passes", "technical"), [(1, False), (1, True), (2, False), (3, True)])
async def test_rejected_turn_never_enters_saved_story(monkeypatch, passes, technical):
    text = "I hand the medal to Lina."
    model = SimpleNamespace(model="local", max_tokens=4096, aexecute_complex_task=AsyncMock())

    async def answer(*_args, **_kwargs):
        assert not db.in_transaction()
        if technical and model.aexecute_complex_task.await_count == passes:
            raise TimeoutError("local stub")
        return {
            "extractions": [event(text, value="given", item_mention="medal", recipient_id="LINA")]
        }

    model.aexecute_complex_task.side_effect = answer
    monkeypatch.setattr(checks.GameMasterLLM, "for_role", lambda *_: model)
    async with TestSessionLocal() as db:
        user, avatar, state, prior = await seed_vn(db)
        user.llm_settings = {**(user.llm_settings or {}), "prose_extraction_passes": passes}
        state.entity_states = {
            **state.entity_states,
            "__chpm__": {"settings": {"reject_impossible_player_items": True}},
        }
        db.add(
            WorldEntity(
                id="MEDAL",
                session_id="session-1",
                entity_type="OBJECT",
                name="medal",
                description="A brass medal.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
                is_portable=True,
            )
        )
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn(text)]
        error = next(chunk for chunk in chunks if chunk.startswith("event: error"))
        payload = json.loads(error.split("data: ", 1)[1])
        assert payload["code"] == (
            "item_check_unavailable" if technical else "impossible_player_item"
        )
        assert payload["retryable"] is technical
        assert payload["quote"] == ("" if technical else text)
        assert model.aexecute_complex_task.await_count == passes
        assert list(await db.scalars(select(ChatMessage.id))) == [prior]
        await db.refresh(avatar)
        assert not avatar.inventory


@pytest.mark.asyncio
async def test_finished_session_never_runs_item_admission(monkeypatch):
    preflight = AsyncMock(side_effect=AssertionError("a finished game cannot start a check"))
    monkeypatch.setattr(checks, "preflight", preflight)
    async with TestSessionLocal() as db:
        user, _, state, prior = await seed_vn(db)
        game = await db.get(GameSession, "session-1")
        game.status = "game_over"
        state.exit_states = {"__terminal_epilogue__": {"game_over_sent": True}}
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn("I give away the medal.")]
        assert any("reached its final ending" in chunk for chunk in chunks)
        preflight.assert_not_awaited()
        assert list(await db.scalars(select(ChatMessage.id))) == [prior]


@pytest.mark.asyncio
async def test_retry_of_admitted_input_skips_another_item_check(monkeypatch):
    text = "I hand over the medal."
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        state.entity_states = {"__chpm__": {"settings": {"reject_impossible_player_items": True}}}
        db.add(TurnReplay(session_id="session-1", before={}, input_text=text, status="pending"))
        db.add(ChatMessage(session_id="session-1", role="user", content=text))
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        await manager.initialize()
        entities = AsyncMock(side_effect=AssertionError("pending input was already admitted"))
        monkeypatch.setattr(checks, "session_objects", entities)
        assert await checks.preflight(manager, text) is None
        entities.assert_not_awaited()
