"""Event and inline-script state must persist together in execution order."""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.gameplay.turn_pass_flow import run_guardrail_chain
from backend.engine.rule_engine import GameEvent
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal
from tests.llm_fakes import RoleLLMFactory
from tests.test_game_loop import _seed_game_context

pytestmark = pytest.mark.asyncio


async def _manager(db):
    user, adventure, avatar, state = await _seed_game_context(db)
    adventure.rule_enforcement_mode = "chat"
    adventure.strict_rules = False
    avatar.inventory = []
    db.add_all(
        [
            WorldScene(id="START", session_id=state.session_id, label="Hall", description="Hall"),
            WorldEntity(
                id="TOKEN",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="PICKABLE",
                name="Token",
                description="Token",
                current_scene_id="START",
                metadata_json={"on_pickup_script": "tw.vars.set('token_picked', True)"},
            ),
            WorldEntity(
                id="GUIDE",
                session_id=state.session_id,
                entity_type="NPC",
                name="Keeper",
                description="Keeper",
                current_scene_id="START",
                hp=10,
                metadata_json={"on_defeat_script": "tw.vars.set('defeat_count', 1)"},
            ),
            WorldEntity(
                id="CHEST",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="CONTAINER",
                name="Iron Chest",
                description="Chest",
                current_scene_id="START",
                metadata_json={"code_to_unlock": "1234"},
            ),
            WorldEntity(
                id="SWITCH",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="SWITCH",
                name="Red Lever",
                description="Lever",
                current_scene_id="START",
                metadata_json={
                    "switch": {
                        "states": ["OFF", "ON"],
                        "initial_state": "OFF",
                        "transitions": [{"from": "OFF", "to": "ON", "gates": {"item": "KEY"}}],
                    }
                },
            ),
        ]
    )
    await db.commit()
    manager = GameTurnManager(db, state.session_id, user)
    await manager.initialize()
    manager.state_applier._ensure_inventory_item_image = AsyncMock()
    return manager


def _pickup_event(**fields):
    return GameEvent.model_validate(
        {
            "new_inventory_items": [{"id": "TOKEN", "name": "Token", "item_type": "PICKABLE"}],
            **fields,
        }
    )


@pytest.mark.parametrize(
    ("event", "key", "value"),
    [
        (_pickup_event(), "token_picked", True),
        (
            GameEvent.model_validate(
                {"updated_entities": [{"entity_id": "GUIDE", "is_defeated": True}]}
            ),
            "defeat_count",
            1,
        ),
    ],
)
async def test_inline_hook_variables_survive_event_commit(setup_test_db, event, key, value):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        await manager._apply_game_event(event.model_copy(deep=True))
        await db.commit()
        session_id = manager.game_id
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
        assert state.entity_states.get("__script_vars__", {}).get(key) == value
        if key == "token_picked":
            assert state.entity_states["TOKEN"]["is_in_inventory"] is True
        else:
            assert state.entity_states["GUIDE"]["is_defeated"] is True


@pytest.mark.parametrize(
    "target", ["CHEST", "chest", " Iron Chest ", "SWITCH", "switch", "Red Lever"]
)
async def test_aliases_pass_through_the_same_locked_target_guards(setup_test_db, target):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        is_chest = target.strip().casefold() in {"chest", "iron chest"}
        canonical = "CHEST" if is_chest else "SWITCH"
        field, attempted, expected = (
            ("locked", False, True) if is_chest else ("switch_state", "ON", "OFF")
        )
        event = GameEvent.model_validate(
            {"updated_entities": [{"entity_id": target, field: attempted}]}
        )
        violations = []
        chunks = [
            chunk async for chunk in run_guardrail_chain(manager, event, "I use it.", violations)
        ]
        assert event.updated_entities[0].entity_id == canonical
        assert manager.state.entity_states.get(canonical, {}).get(field, expected) == expected
        assert violations and chunks


async def test_callbacks_see_prior_event_facts_and_conflicts_follow_execution_order(setup_test_db):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        guide = await db.scalar(select(WorldEntity).where(WorldEntity.id == "GUIDE"))
        token = await db.scalar(select(WorldEntity).where(WorldEntity.id == "TOKEN"))
        guide.metadata_json = {
            "on_defeat_script": "\n".join(
                [
                    "tw.vars.set('seen_hp', tw.npcs.get('GUIDE').hp)",
                    "tw.npcs.get('GUIDE').hp = 7",
                    "tw.flags.set('defeated', True)",
                    "tw.vars.set('order', 'defeat')",
                ]
            )
        }
        token.metadata_json = {
            "on_pickup_script": "\n".join(
                [
                    "tw.vars.set('seen_pickup', tw.objects.get('TOKEN').get_attribute('is_in_inventory'))",
                    "tw.vars.set('seen_order', tw.vars.get('order'))",
                    "tw.vars.set('order', 'pickup')",
                    "tw.npcs.get('GUIDE').set_attribute('description', 'Script description')",
                ]
            )
        }
        event = _pickup_event(
            updated_entities=[
                {
                    "entity_id": "GUIDE",
                    "hp": 0,
                    "is_defeated": True,
                    "description": "Event description",
                }
            ]
        )
        await manager._apply_game_event(event)
        states = manager.state.entity_states
        assert states["__script_vars__"]["seen_hp"] == 0
        assert states["__script_vars__"]["seen_pickup"] is True
        assert states["__script_vars__"]["seen_order"] == "defeat"
        assert states["__script_vars__"]["order"] == "pickup"
        assert states["__switch_story_flags__"]["defeated"] is True
        assert states["GUIDE"] == {
            "hp": 7,
            "is_defeated": True,
            "description": "Script description",
        }
        await db.commit()
        await db.refresh(manager.state)
        assert manager.state.entity_states == states


async def test_full_turn_persists_pickup_and_defeat_hook_variables(setup_test_db, monkeypatch):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        event = _pickup_event(updated_entities=[{"entity_id": "GUIDE", "is_defeated": True}])
        llm = MagicMock(model="local-test", provider="openai")

        async def structured(*args, **kwargs):
            schema = kwargs.get("response_model") or args[2]
            return schema.model_validate(event.model_dump())

        async def stream(*_args, **_kwargs):
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content="The token is yours."))])

        async def return_stream(*args, **kwargs):
            return stream(*args, **kwargs)

        llm.aexecute_complex_task = AsyncMock(side_effect=structured)
        llm.stream_simple_task = AsyncMock(side_effect=return_stream)
        monkeypatch.setattr(
            "backend.api.routes.adventures.gameplay_logic.GameMasterLLM",
            RoleLLMFactory(lambda *args, **kwargs: llm),
        )
        chunks = [
            chunk async for chunk in manager.process_turn("I take the token and defeat the keeper.")
        ]
        assert not any("event: error" in chunk for chunk in chunks)
        session_id = manager.game_id
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
        assert state.entity_states["__script_vars__"] == {"defeat_count": 1, "token_picked": True}


async def test_event_and_hook_changes_rollback_without_mutating_original_snapshot(
    setup_test_db, monkeypatch
):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        manager.state.entity_states = {**manager.state.entity_states, "GUIDE": {"hp": 10}}
        await db.commit()
        original = manager.state.entity_states
        expected = deepcopy(original)

        async def fail(_event, _callback=None):
            raise RuntimeError("Synthetic late event failure")

        monkeypatch.setattr(manager, "_apply_adventure_generator_tools", fail)
        with pytest.raises(RuntimeError, match="Synthetic late event failure"):
            await manager._apply_game_event(
                _pickup_event(updated_entities=[{"entity_id": "GUIDE", "hp": 5}])
            )
        await db.rollback()
        await db.refresh(manager.state)
        assert manager.state.entity_states == expected
        assert original == expected
        await db.refresh(manager.avatar)
        assert manager.avatar.inventory == []
