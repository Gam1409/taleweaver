"""Group travel keeps NPCs on canonical map IDs and emits each move once."""

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.gameplay.turn_adventure_gen import TurnAdventureGenManager
from backend.engine.rule_engine import EntityMovement, GameEvent
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn

ACTION = "Пошлите быстрее в исследовательскую лабораторию"
LABEL = "Исследовательская лаборатория"


class GroupRoles(TurnRoles):
    def __init__(self, *, omit_player=False):
        super().__init__()
        self.omit_player = omit_player

    async def structured(self, *args, **kwargs):
        result = await super().structured(*args, **kwargs)
        if type(result).__name__.startswith("VNProgressionIntent"):
            result.new_scene_id = None if self.omit_player else "LAB"
            result.moved_entities = [
                EntityMovement(entity_id="LINA", to_scene_id=LABEL),
                EntityMovement(entity_id="MIKI", to_scene_id="lab"),
            ]
        return result


async def seed_group(db):
    user, avatar, state, _ = await seed_vn(db)
    lina = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
    lina.moveable = True
    db.add_all(
        [
            WorldEntity(
                id="MIKI",
                session_id="session-1",
                entity_type="NPC",
                name="Мики",
                description="An attentive nurse.",
                current_scene_id="START",
                moveable=True,
            ),
            WorldEntity(
                id="PROFESSOR",
                session_id="session-1",
                entity_type="NPC",
                name="Professor",
                description="A researcher waiting by the centrifuge.",
                current_scene_id="LAB",
            ),
            WorldScene(
                id="LAB", session_id="session-1", label=LABEL, description="Clinical equipment."
            ),
            WorldExit(
                session_id="session-1",
                from_scene_id="START",
                to_scene_id="LAB",
                label="Дверь лаборатории",
                is_locked=False,
            ),
        ]
    )
    await db.commit()
    return user, avatar, state


@pytest.mark.parametrize("omit_player", [False, True])
async def test_group_arrival_normalizes_labels_and_case_before_filtering_scene_cast(
    monkeypatch, omit_player
):
    roles = GroupRoles(omit_player=omit_player)
    install_roles(monkeypatch, roles)
    classifier = AsyncMock(
        return_value={
            "explicit_transition": True,
            "destination_id": "LAB",
            "action_quote": ACTION,
        }
    )
    monkeypatch.setattr(TurnAdventureGenManager, "classify_short_intent", classifier)
    async with TestSessionLocal() as db:
        user, _, state = await seed_group(db)
        events = [
            event async for event in GameTurnManager(db, "session-1", user).process_turn(ACTION)
        ]
        final = final_payload(events)
        assert final["status"] == "success", "".join(events)
        assert final["scene_id"] == "LAB"
        assert {"LINA", "MIKI", "PROFESSOR"} <= {row["id"] for row in final["entities"]}
        await db.refresh(state)
        assert state.entity_states["LINA"]["current_scene_id"] == "LAB"
        assert state.entity_states["MIKI"]["current_scene_id"] == "LAB"
        messages = list(
            await db.scalars(
                select(ChatMessage.content).where(
                    ChatMessage.session_id == "session-1",
                    ChatMessage.role == "system",
                )
            )
        )
        arrivals = [
            text for text in messages if LABEL in text and ("Лина" in text or "Мики" in text)
        ]
        assert len(arrivals) == 2, arrivals
        assert all("moved to" not in text for text in arrivals)
        prompt = json.dumps(roles.prompts, ensure_ascii=False, default=str)
        assert "NPC MOVEMENT RESOLUTION" in prompt
        assert "A researcher waiting by the centrifuge." in prompt
        assert classifier.await_count == 1
        assert "immediate group commands" in classifier.call_args.args[1]


@pytest.mark.parametrize("destination", ["MISSING", "Shared lab"])
async def test_unknown_or_ambiguous_npc_destination_does_not_evict_them(monkeypatch, destination):
    async with TestSessionLocal() as db:
        user, avatar, state = await seed_group(db)
        db.add_all(
            [
                WorldScene(
                    id="OTHER_A",
                    session_id="session-1",
                    label="Shared lab",
                    description="A separate laboratory.",
                ),
                WorldScene(
                    id="OTHER_B",
                    session_id="session-1",
                    label="Shared lab",
                    description="A separate laboratory.",
                ),
            ]
        )
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        manager.state, manager.avatar = state, avatar
        event = GameEvent(
            moved_entities=[EntityMovement(entity_id="MIKI", to_scene_id=destination)]
        )
        errors = await manager.guardrails._enforce_npc_movement_guardrails(event)
        assert errors
        assert not event.moved_entities
        assert state.entity_states.get("MIKI", {}).get("current_scene_id", "START") == "START"


@pytest.mark.parametrize("proposed,confirmed", [(True, False), (False, False), (False, True)])
async def test_player_traversal_requires_its_own_evidence_even_when_npcs_move(proposed, confirmed):
    from types import SimpleNamespace

    from backend.engine.gameplay.movement_intent import confirm_player_movement
    from backend.engine.visual_novel.intent import VNProgressionIntent

    state = SimpleNamespace(current_scene_id="CORRIDOR", entity_states={})
    npc = SimpleNamespace(
        id="RIN", name="Rin", entity_type="NPC", current_scene_id="CORRIDOR", is_hidden=False
    )
    classify = AsyncMock(
        return_value={
            "explicit_transition": confirmed,
            "destination_id": "LAB",
            "action_quote": ACTION,
        }
    )
    manager = SimpleNamespace(
        state=state, adventure_gen=SimpleNamespace(classify_short_intent=classify)
    )
    intent = VNProgressionIntent(
        new_scene_id="LAB" if proposed else None,
        moved_entities=[EntityMovement(entity_id="RIN", to_scene_id="LAB")],
    )
    await confirm_player_movement(
        manager,
        intent,
        user_msg=ACTION,
        scenes=[{"id": "LAB", "label": LABEL}],
        exits=[{"to_scene_id": "LAB", "is_locked": False}],
        entities=[npc],
        history=[],
    )
    assert intent.new_scene_id == ("LAB" if confirmed else None)
    assert bool(intent.moved_entities) == (confirmed or not proposed)
    assert classify.await_count == 1
