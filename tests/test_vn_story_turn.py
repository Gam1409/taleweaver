"""Real VN turn and full replay exercise autonomous NPC movement."""

import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.visual_novel.schema import InteractionPlan
from backend.engine.visual_novel.story_director import STATE_KEY
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn

ACTION = "Я остаюсь здесь и рассматриваю картину. Наш разговор окончен."


class StoryRoles(TurnRoles):
    def __init__(self, *, phase="open", initiative=True):
        super().__init__()
        self.phase = phase
        self.initiative = initiative
        self.focus = None

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if schema is InteractionPlan:
            return await super().structured(*args, **kwargs)
        self.calls.append((schema.__name__, args, kwargs))
        return schema.model_validate(
            {
                "narrative_description": "The player stays to examine the painting.",
                "scene_rhythm": {"phase": self.phase, "evidence": "Наш разговор окончен."},
                "scene_focus": self.focus,
                "story_beat": {
                    "npc_id": "LINA",
                    "kind": "departure",
                    "purpose": "Fetch a letter",
                    "action": "Лина самостоятельно уходит в кабинет за письмом.",
                    "destination_id": "ROOM",
                }
                if self.initiative
                else None,
            }
        )

    async def stream(self, *args, **kwargs):
        self.prompts.append((args, kwargs))
        prompt = json.dumps(kwargs.get("messages", []), ensure_ascii=False)
        reply = (
            "Лина уходит в кабинет. Герой остаётся у картины."
            if "APPROVED NPC INITIATIVE" in prompt
            else "Лина отвечает герою у картины."
        )

        async def chunks():
            yield MagicMock(
                choices=[MagicMock(delta=MagicMock(content=reply), finish_reason="stop")]
            )

        return chunks()


async def seed_story(db):
    user, avatar, state, _ = await seed_vn(db)
    # WorldEntity identity is composite; query the session-owned character explicitly.
    npc = await db.scalar(
        select(WorldEntity).where(WorldEntity.session_id == "session-1", WorldEntity.id == "LINA")
    )
    npc.moveable = True
    npc.allowed_scenes = ["START", "ROOM"]
    db.add(
        WorldScene(
            id="ROOM", session_id="session-1", label="Кабинет", description="A quiet office."
        )
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
    await db.commit()
    return user, avatar, state, npc


@pytest.mark.asyncio
async def test_departure_persists_without_player_following_and_replay_rewinds_direction(
    monkeypatch,
):
    roles = StoryRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state, npc = await seed_story(db)
        before_inventory = list(avatar.inventory or [])
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn(ACTION)]
        assert final_payload(chunks)["status"] == "success", "".join(chunks)
        await db.refresh(state)
        await db.refresh(npc)
        assert state.current_scene_id == "START"
        assert (state.entity_states.get("LINA") or {}).get(
            "current_scene_id", npc.current_scene_id
        ) == "ROOM"
        assert avatar.inventory == before_inventory
        recent = state.entity_states[STATE_KEY]["recent"]
        assert len(recent) == 1
        prompt = json.dumps(roles.prompts, ensure_ascii=False, default=str)
        assert "APPROVED NPC INITIATIVE" in prompt
        assert "VN CONTINUATION AND REPETITION CHECK" in prompt
        # With no NPC left here, the existing social pass also skips its request.
        assert roles.roles.count("small") == 1

        roles.initiative = False
        retry = GameTurnManager(db, "session-1", user)
        chunks = [
            chunk
            async for chunk in retry.process_turn(
                "ignored", replay_message_id=recent[0]["message_id"]
            )
        ]
        assert final_payload(chunks)["status"] == "success", "".join(chunks)
        await db.refresh(state)
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "session-1", WorldEntity.id == "LINA"
            )
        )
        assert STATE_KEY not in state.entity_states
        assert (state.entity_states.get("LINA") or {}).get(
            "current_scene_id", npc.current_scene_id
        ) == "START"
        assert "APPROVED NPC INITIATIVE" not in json.dumps(
            roles.prompts[-1], ensure_ascii=False, default=str
        )


@pytest.mark.asyncio
async def test_npc_can_choose_departure_without_scene_closure_or_player_permission(monkeypatch):
    roles = StoryRoles(phase="engaged")
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, npc = await seed_story(db)
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn("Я молча смотрю на картину.")]
        assert final_payload(chunks)["status"] == "success", "".join(chunks)
        await db.refresh(state)
        await db.refresh(npc)
        assert STATE_KEY in state.entity_states
        assert (state.entity_states.get("LINA") or {}).get(
            "current_scene_id", npc.current_scene_id
        ) == "ROOM"
        assert state.current_scene_id == "START"
        assert "APPROVED NPC INITIATIVE" in json.dumps(
            roles.prompts, ensure_ascii=False, default=str
        )


@pytest.mark.asyncio
async def test_scene_focus_persists_without_initiative_and_full_replay_rewinds_it(monkeypatch):
    roles = StoryRoles(initiative=False)
    roles.focus = {"current_goal": "Find the letter", "open_question": "Who last saw it?"}
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_story(db)
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn("Я спрашиваю про письмо.")]
        assert final_payload(chunks)["status"] == "success", "".join(chunks)
        await db.refresh(state)
        focus = state.entity_states[STATE_KEY]["focus"]
        assert focus["orientation"]["current_goal"] == "Find the letter"
        assert "SCENE ORIENTATION" in json.dumps(roles.prompts, ensure_ascii=False, default=str)
        assert roles.roles.count("small") == 2  # Continuity and social, no extra model call.

        roles.focus = None
        retry = GameTurnManager(db, "session-1", user)
        chunks = [
            chunk
            async for chunk in retry.process_turn("ignored", replay_message_id=focus["message_id"])
        ]
        assert final_payload(chunks)["status"] == "success", "".join(chunks)
        await db.refresh(state)
        assert STATE_KEY not in state.entity_states
        assert "SCENE ORIENTATION" not in json.dumps(
            roles.prompts[-1], ensure_ascii=False, default=str
        )
