"""Dynamic places are bounded, parent-scoped and never created from lore alone."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.dynamic_locations.prompts import intent_schema
from backend.engine.dynamic_locations.schema import (
    PlaceDecision,
    PlaceProposal,
    registry,
    save_registry,
)
from backend.engine.dynamic_locations.service import materialize
from backend.engine.llm_intents import ChatProgressionIntent
from backend.models.world_entity import WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.llm_fakes import RoleLLMFactory
from tests.test_game_loop import _llm_call_text, _seed_game_context

ACTION = "Я увидел таверну и вошёл в неё"


def decision(**changes):
    return PlaceDecision(
        **{
            "arrival_now": True,
            "player_moves": True,
            "local_to_current_scene": True,
            "access_allowed": True,
            "contradicts_world": False,
            "world_scale": "regional",
            "granularity": "site",
            "purpose": "ordinary",
            "action_quote": ACTION,
            "label": "Таверна",
            "description": "Небольшая таверна с деревянными столами.",
            **changes,
        }
    )


async def setup(db, scale="regional"):
    user, adv, avatar, state = await _seed_game_context(db)
    adv.strict_rules = False
    adv.rule_enforcement_mode = "chat"
    save_registry(state, {"policy": {"enabled": True, "scale": scale, "generate_images": False}})
    db.add_all(
        [
            WorldScene(session_id="session-1", id="START", label="Лес", description="Лес"),
            WorldScene(session_id="session-1", id="CITY", label="Город", description="Город"),
        ]
    )
    await db.commit()
    return SimpleNamespace(
        db=db, user=user, adventure=adv, state=state, game_id="session-1"
    ), avatar


async def apply(manager, result, action=ACTION, recent=""):
    scenes = list(
        (
            await manager.db.scalars(
                select(WorldScene).where(WorldScene.session_id == manager.game_id)
            )
        ).all()
    )
    exits = list(
        (
            await manager.db.scalars(
                select(WorldExit).where(WorldExit.session_id == manager.game_id)
            )
        ).all()
    )
    return await materialize(
        manager,
        PlaceProposal(label="Таверна", action_quote=action),
        result,
        action,
        recent,
        scenes,
        exits,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"arrival_now": False},
        {"player_moves": False},
        {"local_to_current_scene": False},
        {"access_allowed": False},
        {"contradicts_world": True},
        {"granularity": "detail"},
        {"action_quote": "fabricated evidence"},
        {"granularity": "room"},
    ],
)
async def test_rejected_or_incidental_place_does_not_create_scene(change):
    async with TestSessionLocal() as db:
        manager, _ = await setup(db)
        assert await apply(manager, decision(**change)) is None
        assert not registry(manager.state).get("places")
        assert len(list((await db.scalars(select(WorldScene))).all())) == 2


async def test_same_tavern_name_in_forest_and_city_is_not_global_identity():
    async with TestSessionLocal() as db:
        manager, _ = await setup(db)
        forest = await apply(manager, decision())
        assert forest
        assert await apply(manager, decision()) == forest
        manager.state.current_scene_id = "CITY"
        city = await apply(manager, decision())
        assert city and city != forest
        places = registry(manager.state)["places"]
        assert places[forest]["parent_id"] == "START"
        assert places[city]["parent_id"] == "CITY"
        assert len(places) == 2


@pytest.mark.parametrize(
    "scale,purpose,quote,allowed",
    [
        ("regional", "ordinary", "", False),
        ("building", "ordinary", "", True),
        ("regional", "overnight", "Комната оплачена на ночь", True),
        ("regional", "investigation", "В комнате найдены следы", True),
        ("regional", "persistent", "invented justification", False),
    ],
)
async def test_room_granularity_depends_on_world_scale_and_evidenced_purpose(
    scale, purpose, quote, allowed
):
    async with TestSessionLocal() as db:
        manager, _ = await setup(db, scale)
        result = await apply(
            manager,
            decision(granularity="room", purpose=purpose, purpose_quote=quote),
            recent="Комната оплачена на ночь. В комнате найдены следы.",
        )
        assert bool(result) is allowed


async def test_locked_known_place_cannot_be_duplicated():
    async with TestSessionLocal() as db:
        manager, _ = await setup(db)
        db.add(WorldScene(id="INN", session_id="session-1", label="Таверна", description="Закрыто"))
        db.add(
            WorldExit(
                session_id="session-1",
                from_scene_id="START",
                to_scene_id="INN",
                label="Дверь",
                is_locked=True,
            )
        )
        await db.flush()
        assert await apply(manager, decision()) is None
        assert not registry(manager.state).get("places")


async def test_enabled_chat_turn_creates_scene_before_narration_and_updates_state(monkeypatch):
    async with TestSessionLocal() as db:
        manager, _ = await setup(db)
        llm = MagicMock()
        llm.aexecute_complex_task = AsyncMock(
            return_value=intent_schema(ChatProgressionIntent, manager.state)(
                new_local_place=PlaceProposal(label="Таверна", action_quote=ACTION)
            )
        )

        async def stream(*_args, **_kwargs):
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content="Вы вошли в таверну."))])

        llm.stream_simple_task = AsyncMock(return_value=stream())
        monkeypatch.setattr(
            "backend.api.routes.adventures.gameplay_logic.GameMasterLLM",
            RoleLLMFactory(lambda *args, **kwargs: llm),
        )
        confirmation = MagicMock()
        confirmation.aexecute_complex_task = AsyncMock(return_value=decision())
        monkeypatch.setattr(
            "backend.engine.dynamic_locations.service.GameMasterLLM",
            RoleLLMFactory(lambda *args, **kwargs: confirmation),
        )
        chunks = [
            c async for c in GameTurnManager(db, "session-1", manager.user).process_turn(ACTION)
        ]
        await db.refresh(manager.state)
        target = manager.state.current_scene_id
        assert target.startswith("dyn_")
        assert registry(manager.state)["places"][target]["parent_id"] == "START"
        assert target in _llm_call_text(llm.stream_simple_task.await_args_list[0])
        assert '"scene_changed": true' in _llm_call_text(llm.stream_simple_task.await_args_list[0])
        assert "event: state" in "".join(chunks)
        assert confirmation.aexecute_complex_task.await_count == 1


async def test_disabled_has_no_extra_schema_or_calls():
    async with TestSessionLocal() as db:
        manager, _ = await setup(db)
        manager.state.entity_states = {}
        assert intent_schema(ChatProgressionIntent, manager.state) is ChatProgressionIntent


async def test_place_and_depth_limits_bound_expansion():
    from backend.engine.dynamic_locations.schema import MAX_CHILDREN, MAX_DEPTH

    async with TestSessionLocal() as db:
        manager, _ = await setup(db, "building")
        data = registry(manager.state)
        save_registry(
            manager.state,
            {
                **data,
                "places": {str(i): {"parent_id": "START", "depth": 1} for i in range(MAX_CHILDREN)},
            },
        )
        assert await apply(manager, decision()) is None
        save_registry(
            manager.state, {**data, "places": {"START": {"parent_id": "other", "depth": MAX_DEPTH}}}
        )
        assert await apply(manager, decision(granularity="room")) is None


async def test_confirmation_timeout_and_malformed_response_leave_world_untouched(monkeypatch):
    from backend.engine.dynamic_locations.service import resolve_proposal

    async with TestSessionLocal() as db:
        manager, _ = await setup(db)
        llm = MagicMock()
        llm.aexecute_complex_task = AsyncMock(side_effect=TimeoutError())
        monkeypatch.setattr(
            "backend.engine.dynamic_locations.service.GameMasterLLM",
            RoleLLMFactory(lambda *args, **kwargs: llm),
        )
        intent = intent_schema(ChatProgressionIntent, manager.state)(
            new_local_place=PlaceProposal(label="Таверна", action_quote=ACTION)
        )
        await resolve_proposal(manager, intent, ACTION, [], "Russian")
        assert intent.new_scene_id is None
        assert not registry(manager.state).get("places")
        llm.aexecute_complex_task.side_effect = None
        llm.aexecute_complex_task.return_value = {"arrival_now": True}
        await resolve_proposal(manager, intent, ACTION, [], "Russian")
        assert intent.new_scene_id is None
        assert not registry(manager.state).get("places")


async def test_known_room_can_be_reused_even_when_new_incidental_rooms_are_disabled():
    async with TestSessionLocal() as db:
        manager, _ = await setup(db, "regional")
        db.add(
            WorldScene(id="ROOM", session_id="session-1", label="Комната", description="Комната")
        )
        db.add(
            WorldExit(
                session_id="session-1",
                from_scene_id="START",
                to_scene_id="ROOM",
                label="Дверь",
                is_locked=False,
            )
        )
        await db.flush()
        assert (
            await apply(manager, decision(existing_scene_id="ROOM", granularity="room")) == "ROOM"
        )
        assert not registry(manager.state).get("places")
