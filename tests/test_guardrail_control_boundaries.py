"""Canonical proposals, chat history and player-facing notices have separate owners."""

from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.gameplay.guardrails.manager import TurnGuardrailsManager
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.gameplay.turn_pass_flow import run_guardrail_chain
from backend.engine.rule_engine import GameEvent
from backend.engine.turn_controls import begin, rule_rejections
from backend.models.chat import ChatMessage
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_constructable_runtime import _seed


def item(identifier, **kwargs):
    return WorldEntity(
        id=identifier,
        name=identifier,
        entity_type="OBJECT",
        description="Fixture",
        current_scene_id="START",
        **kwargs,
    )


async def test_guard_feedback_uses_outcome_and_chat_cannot_reveal_or_commit():
    async with TestSessionLocal() as db:
        user, _, avatar, state = await _seed(db)
        avatar.inventory = [{"id": identifier, "name": identifier} for identifier in ("A", "B")]
        result = item(
            "RESULT",
            item_type="CONSTRUCTABLE",
            is_hidden=True,
            combination_ingredients=["A", "B"],
            metadata_json={"on_craft_success_text": "Blocked-looking success text."},
        )
        for row in [result, item("MAP", is_hidden=True), item("A"), item("B")]:
            row.session_id = state.session_id
            db.add(row)
        await db.commit()
        game_id, user_id = state.session_id, user.id
        manager = GameTurnManager(db, game_id, user)
        assert await manager.initialize()
        for role in ("user", "assistant", "system"):
            await manager._save_chat_message(role, "There is no ID: MAP or ID: UNKNOWN here.")
        assert "UNKNOWN" not in (state.entity_states or {})
        assert "is_hidden" not in (state.entity_states or {}).get("MAP", {})
        await db.rollback()
    async with TestSessionLocal() as db:
        assert not (await db.scalars(select(ChatMessage))).all()
        manager = GameTurnManager(db, game_id, await db.get(User, user_id))
        assert await manager.initialize()
        begin(manager)
        event = GameEvent(
            combination_intent=True, combination_result_id="RESULT", discovered_entity_ids=["MAP"]
        )
        violations = []
        stream = [
            chunk
            async for chunk in run_guardrail_chain(manager, event, "Assemble them.", violations)
        ]
        assert any("Revealed MAP" in chunk for chunk in stream)
        assert set(event.removed_inventory_item_ids) == {"A", "B"}
        assert rule_rejections(manager, violations) == []
        transcript = Counter((await db.scalars(select(ChatMessage.content))).all())
        assert transcript["Blocked-looking success text."] == transcript["Revealed MAP"] == 1


@pytest.mark.parametrize(
    ("fields", "words", "expected"),
    [
        ({"combination_ingredient_ids": ["PIN", "CAP"]}, "Соединяю их.", "SECOND"),
        (
            {"combination_ingredient_ids": ["PIN", "CAP"], "combination_result_id": "FIRST"},
            "Assemble.",
            None,
        ),
        ({"combination_result_id": "MISSING"}, "combine PIN and CAP", None),
        ({}, "combine PIN", None),
        ({}, "combine PIN and CAP", "SECOND"),
    ],
)
async def test_shared_ingredient_identifies_only_one_complete_recipe(fields, words, expected):
    state = SimpleNamespace(current_scene_id="START", entity_states={})
    avatar = SimpleNamespace(inventory=[{"id": name} for name in ("PIN", "CAP", "HEAD")])
    guard = TurnGuardrailsManager(SimpleNamespace(state=state, avatar=avatar, game_id="S"))
    recipes = [
        item("FIRST", is_hidden=True, combination_ingredients=["PIN", "HEAD"]),
        item("SECOND", is_hidden=True, combination_ingredients=["PIN", "CAP"]),
    ]
    for order in (recipes, recipes[::-1]):
        event = GameEvent(combination_intent=True, **fields)
        cs = guard._crafting_state(order)
        await guard._try_craft(event, order, cs, words)
        assert cs.constructed == ({expected} if expected else set())
        assert set(event.removed_inventory_item_ids or []) == (
            {"PIN", "CAP"} if expected else set()
        )


async def test_reward_requires_the_referenced_id_in_the_current_scene():
    fixture = SimpleNamespace(
        state=SimpleNamespace(
            current_scene_id="START",
            entity_states={"REMOTE_KEY": {"current_scene_id": "AWAY"}},
            quests=[
                {"id": "WORD", "goal": "Listen for the key change.", "description": "REMOTE_KEY"},
                {"id": "REF", "goal": "Find REMOTE_KEY."},
            ],
        ),
        avatar=SimpleNamespace(inventory=[], equipment={}),
    )
    guard = TurnGuardrailsManager(fixture)
    remote = item("REMOTE_KEY")
    nearby = item("OTHER_KEY")
    remote.name = nearby.name = "Key"
    guard._session_entities = AsyncMock(return_value=[remote, nearby])
    event = GameEvent(completed_quest_ids=["WORD", "REF"])
    await guard._enforce_quest_and_award_guardrails(event)
    assert event.completed_quest_ids == ["WORD"]


def test_parent_reference_cannot_reveal_a_partial_id():
    from backend.engine.gameplay.guardrails.reveals import _parent_reveals

    child = item("CHILD", spatial_position="behind ##DOORWAY")
    event = GameEvent(updated_entities=[{"entity_id": "DOOR", "description": "Open"}])
    assert not _parent_reveals(event, child, {})
    child.spatial_position = "behind ##door"
    assert _parent_reveals(event, child, {})


async def test_failed_craft_preserves_ingredients_and_keeps_unrelated_changes():
    state = SimpleNamespace(current_scene_id="START", entity_states={})
    guard = TurnGuardrailsManager(
        SimpleNamespace(state=state, avatar=SimpleNamespace(inventory=[{"id": "PIN"}]))
    )
    recipe = item("RESULT", is_hidden=True, combination_ingredients=["PIN", "CAP"])
    event = GameEvent(
        combination_intent=True,
        combination_result_id="RESULT",
        removed_inventory_item_ids=["PIN", "OTHER"],
        deleted_entities=["PIN"],
        updated_entities=[{"entity_id": "PIN", "is_hidden": True, "description": "Bent"}],
    )
    cs = guard._crafting_state([recipe])
    await guard._try_craft(event, [recipe], cs, "")
    assert not cs.constructed and cs.messages
    assert event.removed_inventory_item_ids == ["OTHER"]
    assert event.deleted_entities == []
    assert (
        event.updated_entities[0].is_hidden is None
        and event.updated_entities[0].description == "Bent"
    )
