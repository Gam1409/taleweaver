"""VN persistence rejects mechanical outcomes even with stale imported flags."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.unlock_service import award_session_unlock_xp
from backend.engine.rule_engine import GameEvent, WorldEntityUpdate
from backend.engine.visual_novel.event_policy import enforce_vn_event_policy
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity


def test_vn_event_policy_preserves_continuity_but_removes_combat():
    event = GameEvent(
        hp_change=-100,
        mana_change=-30,
        stamina_change=-20,
        game_over=True,
        game_completed=True,
        sequence_completed=True,
        completed_quest_ids=["Q"],
        earned_award_keys=["A"],
        new_status_effects=["Poisoned"],
        new_scene_id="CAFE",
        remember_notes=["Meet tomorrow"],
        updated_entities=[
            WorldEntityUpdate(entity_id="LENA", hp=0, is_defeated=True, notes="Keeps her promise")
        ],
    )
    enforce_vn_event_policy(event, {"rule_enforcement_mode": "vn", "strict_rules": True})
    assert (event.hp_change, event.mana_change, event.stamina_change) == (0, 0, 0)
    assert not any((event.game_over, event.game_completed, event.sequence_completed))
    assert event.completed_quest_ids is event.earned_award_keys is event.new_status_effects is None
    assert event.new_scene_id == "CAFE"
    assert event.remember_notes == ["Meet tomorrow"]
    assert event.updated_entities[0].notes == "Keeps her promise"
    assert event.updated_entities[0].is_defeated is event.updated_entities[0].hp is None


def test_event_policy_does_not_change_legacy_chat():
    event = GameEvent(completed_quest_ids=["Q"], earned_award_keys=["A"], hp_change=-10)
    before = event.model_dump()
    enforce_vn_event_policy(event, {"rule_enforcement_mode": "chat"})
    assert event.model_dump() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, reward", [("vn", 0), ("chat", 80), ("rpg", 80)])
async def test_direct_unlock_xp_respects_mode(mode, reward):
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(rule_enforcement_mode=mode, strict_rules=True)
    avatar = SimpleNamespace(exp=25)
    actual = await award_session_unlock_xp(
        db, SimpleNamespace(template_id="template"), avatar, {"exp_reward": 80}
    )
    assert actual == reward
    assert avatar.exp == 25 + reward


@pytest.mark.asyncio
async def test_direct_unlock_uses_snapshot_mode_without_template():
    db = AsyncMock()
    db.get.return_value = None
    state = SessionState(
        template_id=None,
        entity_states={"__manifest_snapshot__": {"adventure": {"rule_enforcement_mode": "vn"}}},
    )
    avatar = SimpleNamespace(exp=25)
    assert await award_session_unlock_xp(db, state, avatar, {"exp_reward": 80}) == 0
    assert avatar.exp == 25


async def _seed_vn(db):
    user = User(username="vn-policy-player", hashed_password="pw", role="user", earned_awards=[])
    db.add(user)
    await db.flush()
    adventure = AdventureTemplate(
        id="vn-policy",
        owner_id=user.id,
        title="A reunion",
        rule_enforcement_mode="vn",
        strict_rules=True,
        can_damage_npcs=True,
        npcs_can_damage_protagonist=True,
        awards=[{"key": "A", "required_scene_id": "START"}],
        sequences=[{"id": "S", "order": 1, "required_scene_id": "START", "exp_reward": 100}],
        completed_guard_expression="True",
    )
    db.add(adventure)
    avatar = Avatar(
        id="vn-avatar",
        template_id=adventure.id,
        user_id=user.id,
        name="Alex",
        role="Neighbour",
        hp=100,
        mana=30,
        stamina=50,
        exp=25,
    )
    db.add(avatar)
    await db.flush()
    db.add(
        GameSession(id="vn-session", user_id=user.id, template_id=adventure.id, avatar_id=avatar.id)
    )
    await db.flush()
    state = SessionState(
        session_id="vn-session",
        user_id=user.id,
        template_id=adventure.id,
        avatar_id=avatar.id,
        current_scene_id="START",
        quests=[{"id": "Q", "status": "open", "required_scene_id": "START", "exp_reward": 90}],
        entity_states={},
    )
    db.add(state)
    db.add(
        WorldEntity(
            id="LENA",
            session_id="vn-session",
            entity_type="NPC",
            name="Lena",
            description="A familiar neighbour",
            current_scene_id="START",
        )
    )
    await db.commit()
    return user, adventure, avatar, state


@pytest.mark.asyncio
async def test_applier_skips_stale_vn_quests_awards_combat_and_endings(setup_test_db, monkeypatch):
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        user, adventure, avatar, state = await _seed_vn(db)
        manager = GameTurnManager(db, "vn-session", user)
        await manager.initialize()
        evaluate = Mock(side_effect=AssertionError("VN must not evaluate RPG quests"))
        monkeypatch.setattr(
            "backend.api.routes.adventures.turn_state_applier.QuestManager.evaluate_quests",
            evaluate,
        )
        event = GameEvent(
            hp_change=-100,
            game_over=True,
            game_completed=True,
            sequence_completed=True,
            completed_quest_ids=["Q"],
            earned_award_keys=["A"],
            updated_entities=[
                WorldEntityUpdate(entity_id="LENA", hp=0, is_defeated=True, notes="Waiting")
            ],
        )
        messages = await manager._apply_game_event(event)
        assert not evaluate.called
        assert avatar.exp == 25
        assert avatar.hp == 100
        assert user.earned_awards == []
        assert state.quests[0]["status"] == "open"
        assert not state.entity_states["LENA"].get("is_defeated")
        assert state.entity_states["LENA"]["notes"] == "Waiting"
        assert not event.game_over and not event.game_completed
        assert not any("XP" in message or "Award" in message for message in messages)
