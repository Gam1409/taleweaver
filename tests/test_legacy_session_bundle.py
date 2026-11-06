"""Legacy inline saves restore a playable, isolated session and its narrative sources."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.core.config import settings
from backend.models.adventure_template import AdventureTemplate
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from tests.conftest import TestSessionLocal


@pytest.fixture
def bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    return {
        "version": "1.0",
        "type": "SESSION_BUNDLE",
        "adventure": {"title": "Legacy save", "rule_enforcement_mode": "vn"},
        "scenes": [{"id": "ROOM", "name": "Room", "description": "A quiet room."}],
        "exits": [],
        "entities": [
            {
                "id": "GUIDE",
                "entity_type": "NPC",
                "name": "Guide",
                "description": "A watchful guide.",
                "current_scene_id": "ROOM",
                "character": "Independent",
                "metadata_json": {"marker": "keep"},
            }
        ],
        "game_state": {
            "current_scene_id": "ROOM",
            "entity_states": {},
            "quests": [{"id": "q", "status": "active"}],
            "in_game_time": 720,
            "active_sequence_id": "part-two",
            "active_sequence_order": 2,
            "world_memories": [{"text": "The guide kept the key."}],
            "compressed_history": {
                "summary": "Earlier events",
                "last_compressed_msg_id": "old-message",
            },
        },
        "avatar": {
            "name": "Hero",
            "hp": 50,
            "stamina": 50,
            "mana": 0,
            "stats": {},
            "inventory": [],
        },
        "chat_history": [
            {
                "id": "old-message",
                "role": "assistant",
                "content": "The guide kept the key.",
                "scene_id": "ROOM",
            }
        ],
    }


async def test_inline_save_opens_with_owned_state_and_preserved_history(auth_client, bundle):
    result = await auth_client.post("/api/adventures/import/session-bundle", json=bundle)
    assert result.status_code == 200, result.text
    template_id = result.json()["adventure_id"]
    async with TestSessionLocal() as db:
        game = await db.scalar(select(GameSession).where(GameSession.template_id == template_id))
        state = await db.scalar(select(SessionState).where(SessionState.session_id == game.id))
        assert (state.user_id, state.template_id, state.avatar_id) == (
            game.user_id,
            template_id,
            game.avatar_id,
        )
        assert state.quests == bundle["game_state"]["quests"]
        assert state.active_sequence_id == "part-two" and state.active_sequence_order == 2
        messages = list(
            await db.scalars(select(ChatMessage).where(ChatMessage.session_id == game.id))
        )
        assert len(messages) == 1 and messages[0].id != "old-message"
        assert state.compressed_history["last_compressed_msg_id"] == messages[0].id
        assert state.world_memories == bundle["game_state"]["world_memories"]
        game_id = game.id
    opened = await auth_client.get(f"/api/adventures/{game_id}/chat")
    assert opened.status_code == 200, opened.text
    assert "The guide kept the key." in opened.text


async def test_inline_save_materializes_complete_session_world(auth_client, bundle):
    response = await auth_client.post("/api/adventures/import/session-bundle", json=bundle)
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        game = await db.scalar(
            select(GameSession).where(GameSession.template_id == response.json()["adventure_id"])
        )
        scene = await db.scalar(select(WorldScene).where(WorldScene.session_id == game.id))
        guide = await db.scalar(
            select(WorldEntity).where(WorldEntity.session_id == game.id, WorldEntity.id == "GUIDE")
        )
        assert scene is not None and scene.id == "ROOM"
        assert guide is not None and guide.character == "Independent"
        assert guide.metadata_json["marker"] == "keep"


async def test_inline_save_rebinds_exit_ids_and_ignores_foreign_scope_fields(auth_client, bundle):
    bundle["entities"][0].update(
        pk=987654, template_id="foreign-template", session_id="foreign-session"
    )
    bundle["game_state"].update(
        user_id="foreign-owner", avatar_id="foreign-avatar", template_id="foreign-template"
    )
    bundle["exits"] = [
        {"id": "old-exit", "from_scene_id": "ROOM", "to_scene_id": "ROOM", "label": "Door"}
    ]
    bundle["game_state"]["exit_states"] = {"old-exit": {"is_locked": False}}
    response = await auth_client.post("/api/adventures/import/session-bundle", json=bundle)
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        game = await db.scalar(
            select(GameSession).where(GameSession.template_id == response.json()["adventure_id"])
        )
        state = await db.scalar(select(SessionState).where(SessionState.session_id == game.id))
        guide = await db.scalar(select(WorldEntity).where(WorldEntity.session_id == game.id))
        door = await db.scalar(select(WorldExit).where(WorldExit.session_id == game.id))
        assert door.id != "old-exit" and state.exit_states == {door.id: {"is_locked": False}}
        assert guide.pk != 987654 and guide.template_id is None
        assert state.avatar_id == game.avatar_id and state.user_id == game.user_id


@pytest.mark.parametrize("missing", ["avatar", "game_state"])
async def test_partial_inline_save_is_rejected_without_publishing_a_template(
    auth_client, bundle, missing
):
    incomplete = deepcopy(bundle)
    incomplete[missing] = None
    response = await auth_client.post("/api/adventures/import/session-bundle", json=incomplete)
    assert response.status_code == 400
    async with TestSessionLocal() as db:
        assert (
            await db.scalar(
                select(AdventureTemplate).where(AdventureTemplate.title == "Legacy save")
            )
            is None
        )
