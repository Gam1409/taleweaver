"""Exercise the real turn pipeline with deterministic local role doubles."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.scene_illustrations.snapshots import REGISTRY_KEY
from backend.engine.visual_novel.schema import STATE_KEY, InteractionPlan, SocialProposal
from backend.engine.visual_novel.state import load_state
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_game_loop import _seed_game_context

PRIOR = "Лина и герой вместе починили сломанную полку."
NARRATION = 'Лина: "Спасибо. Теперь можно спокойно поговорить."'
ACTION = "Я спрашиваю Лину, что она хочет делать дальше."


class TurnRoles:
    def __init__(self, social_failure=False):
        self.calls = []
        self.prompts = []
        self.roles = []
        self.social_failure = social_failure

    def for_role(self, _user, role, **_kwargs):
        self.roles.append(role)
        return SimpleNamespace(
            model=f"local-{role}",
            provider="openai",
            aexecute_complex_task=self.structured,
            stream_simple_task=self.stream,
        )

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        self.calls.append((schema.__name__, args, kwargs))
        if schema is InteractionPlan:
            if self.social_failure:
                raise TimeoutError("Simulated slow Small model")
            return InteractionPlan(
                reactions=[
                    SocialProposal(
                        npc_id="LINA",
                        source="scene_context",
                        evidence=PRIOR,
                        basis="performed_interaction",
                        event="cooperation",
                        emotion="pleased",
                        intention="listen",
                    )
                ]
            )
        assert schema.__name__.startswith("VNProgressionIntent")
        fields = set(schema.model_fields)
        assert not fields & {
            "completed_quest_ids",
            "earned_award_keys",
            "game_over",
            "game_completed",
            "hp_change",
            "stamina_change",
            "new_sequence_id",
        }
        return schema.model_validate(
            {
                "narrative_description": "The player asks a question.",
                "completed_quest_ids": ["OLD_QUEST"],
                "earned_award_keys": ["OLD_AWARD"],
                "hp_change": -99,
            }
        )

    async def stream(self, *args, **kwargs):
        self.prompts.append((args, kwargs))

        async def chunks():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=NARRATION))])

        return chunks()


def install_roles(monkeypatch, roles):
    monkeypatch.setattr("backend.api.routes.adventures.gameplay_logic.GameMasterLLM", roles)
    monkeypatch.setattr("backend.engine.visual_novel.social.GameMasterLLM", roles)
    monkeypatch.setattr(
        "backend.api.routes.adventures.gameplay_logic.schedule_npc_journal", lambda *_: None
    )
    monkeypatch.setattr(
        "backend.api.routes.adventures.gameplay_logic.schedule_images", lambda *_: None
    )


async def seed_vn(db):
    user, adventure, avatar, state = await _seed_game_context(db)
    adventure.rule_enforcement_mode = "vn"
    adventure.strict_rules = True  # A stale imported flag must not enable mechanics.
    adventure.is_adventure_generator = False
    adventure.language = "English"
    adventure.original_manifest = {
        "scripts": [
            {"trigger": "on_turn_start", "code": "raise RuntimeError('legacy RPG script')"}
        ],
        "init_script": "raise RuntimeError('legacy init')",
    }
    avatar.description = "A traveler in a green scarf."
    user.default_language = "English"
    user.earned_awards = []
    user.tts_settings = {"use_vocal_tags": False}
    adventure.awards = [{"key": "OLD_AWARD", "title": "Legacy award", "tier": "bronze"}]
    state.quests = [
        {"id": "OLD_QUEST", "title": "Legacy quest", "status": "open", "exp_reward": 500}
    ]
    state.enable_history_compression = False
    state.entity_states = {"__vn_settings__": {"pace": "leisurely"}}
    game = await db.get(GameSession, "session-1")
    game.content_language = "Russian"
    db.add(
        WorldScene(
            id="START", session_id=game.id, label="Таверна", description="Quiet common room."
        )
    )
    db.add_all(
        [
            WorldEntity(
                id="LINA",
                session_id=game.id,
                entity_type="NPC",
                name="Лина",
                description="A woman in a blue coat.",
                character="Values honesty.",
                goal="SECRET_GOAL_NOT_PUBLIC",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
                inventory=[{"id": "HIDDEN_RING", "name": "Hidden ring"}],
            ),
            WorldEntity(
                id="ABSENT",
                session_id=game.id,
                entity_type="NPC",
                name="Далёкий",
                description="Must not enter the current picture.",
                current_scene_id="FOREST",
                is_hidden=False,
                is_in_inventory=False,
            ),
        ]
    )
    previous = ChatMessage(session_id=game.id, role="assistant", content=PRIOR, scene_id="START")
    db.add(previous)
    await db.commit()
    return user, avatar, state, previous.id


def final_payload(chunks):
    final = next(chunk for chunk in chunks if chunk.startswith("event: final"))
    return json.loads(next(line[5:] for line in final.splitlines() if line.startswith("data:")))


@pytest.mark.asyncio
async def test_real_vn_turn_roles_language_social_state_snapshot_and_reload(monkeypatch):
    roles = TurnRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state, source_id = await seed_vn(db)
        before_hp, before_xp = avatar.hp, avatar.exp
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn(ACTION)]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        payload = final_payload(chunks)
        assert manager._get_script_runner().scripts == []
        assert (
            await manager._execute_inline_script(
                "raise RuntimeError('must not run')", "on_turn_start", "LINA"
            )
            == []
        )
        await db.refresh(state)
        await db.refresh(avatar)
        assert (avatar.hp, avatar.exp) == (before_hp, before_xp)
        assert state.quests[0]["status"] == "open"
        assert user.earned_awards == []
        assert [call[0] for call in roles.calls] == ["VNProgressionIntent", "InteractionPlan"]
        assert roles.roles.count("small") == 2
        assert roles.roles.count("complex") == 1
        prompt = json.dumps(roles.prompts, ensure_ascii=False, default=str)
        assert "VISUAL NOVEL NARRATION CONTRACT" in prompt
        assert "PACING: LEISURELY" in prompt
        assert "RUSSIAN" in prompt
        assert "sitcom" not in prompt.lower()
        messages = list(
            (
                await db.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == "session-1")
                    .order_by(ChatMessage.created_at, ChatMessage.id)
                )
            ).all()
        )
        player = next(message for message in messages if message.role == "user")
        reply = next(message for message in messages if message.content == NARRATION)
        social = load_state(state)
        assert social.processed_message_ids == [player.id]
        assert manager._vn_player_message_id == player.id
        assert social.characters["LINA"].memories[0].source_message_id == source_id
        assert social.characters["LINA"].relationship.respect == 2
        snapshot = state.entity_states[REGISTRY_KEY]["snapshots"][reply.id]
        assert snapshot["narration"] == NARRATION
        assert snapshot["scene_id"] == "START"
        assert snapshot["visible_facts"]["characters"] == [
            {"id": avatar.id, "name": "Hero", "appearance": "A traveler in a green scarf."},
            {"id": "LINA", "name": "Лина", "appearance": "A woman in a blue coat."},
        ]
        assert "SECRET_GOAL_NOT_PUBLIC" not in json.dumps(payload, ensure_ascii=False)
        assert "HIDDEN_RING" not in json.dumps(snapshot, ensure_ascii=False)
        stored_id, stored_social, reply_id = state.id, state.entity_states[STATE_KEY], reply.id
    async with TestSessionLocal() as db:
        reloaded = await db.get(SessionState, stored_id)
        assert reloaded.entity_states[STATE_KEY] == stored_social
        assert reloaded.entity_states[REGISTRY_KEY]["snapshots"][reply_id]["narration"] == NARRATION


@pytest.mark.asyncio
async def test_real_vn_turn_social_timeout_keeps_story_playable(monkeypatch):
    roles = TurnRoles(social_failure=True)
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _avatar, state, _source_id = await seed_vn(db)
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn(ACTION)]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        assert final_payload(chunks)["status"] == "success"
        assert await db.scalar(select(ChatMessage.id).where(ChatMessage.content == NARRATION))
        await db.refresh(state)
        assert STATE_KEY not in state.entity_states
        assert len(state.entity_states[REGISTRY_KEY]["snapshots"]) == 1


@pytest.mark.asyncio
async def test_reopened_vn_session_continues_memory_without_replaying_old_evidence(monkeypatch):
    roles = TurnRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _avatar, state, _source_id = await seed_vn(db)
        manager = GameTurnManager(db, "session-1", user)
        first = [chunk async for chunk in manager.process_turn(ACTION)]
        assert final_payload(first)["status"] == "success"
        state_id = state.id
        initial = load_state(state).characters["LINA"].model_dump()
    async with TestSessionLocal() as db:
        manager = GameTurnManager(db, "session-1", user)
        second = [chunk async for chunk in manager.process_turn("Я жду ответа Лины.")]
        assert final_payload(second)["status"] == "success"
        reloaded = await db.get(SessionState, state_id)
        social = load_state(reloaded)
        # The double deliberately repeats a quote from the older turn. It is not
        # in the current assistant narration and cannot earn a second event.
        assert social.characters["LINA"].model_dump() == initial
        assert len(social.processed_message_ids) == 2
        assert len(set(social.processed_message_ids)) == 2
        assert len(reloaded.entity_states[REGISTRY_KEY]["snapshots"]) == 2
