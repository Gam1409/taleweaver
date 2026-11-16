"""World clothing, possessions, snapshots and portrait options survive controller modes."""

import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.engine.chpm import inference, rendering
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.npc_presentation.settings import KEY as PORTRAIT_KEY
from backend.engine.scene_illustrations.snapshots import registry_of
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_chpm_turn import ChpmRoles
from tests.test_clothing_runtime import ACTION, action, item, profile
from tests.test_vn_turn_integration import NARRATION, final_payload, install_roles, seed_vn


class FeatureRoles(ChpmRoles):
    async def structured(self, *args, **kwargs):
        result = await super().structured(*args, **kwargs)
        if type(result).__name__.startswith("VNProgressionIntent"):
            result.wardrobe_actions = [action()]
        return result

    async def stream(self, *args, **kwargs):
        original = await super().stream(*args, **kwargs)

        async def chunks():
            async for part in original:
                yield part
            footer = '<npc-state>{"npcs":[{"npc_id":"LINA","emotion":"interest","intensity":65,"thought":"Let us continue."}]}</npc-state>'
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=footer))])

        return chunks()


@pytest.mark.parametrize("mode", ["off", "shadow", "live"])
async def test_independent_features_use_current_world_facts_in_every_controller_mode(
    monkeypatch, mode
):
    roles = FeatureRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        avatar.inventory, avatar.visual_profile = [item()], profile()
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(settings=Settings(mode=mode, actor_ids=["LINA"])).model_dump(),
            PORTRAIT_KEY: {"emotion_palette": True, "character_thoughts": True},
        }
        await db.commit()
        host = GameTurnManager(db, state.session_id, user)
        events = [part async for part in host.process_turn(ACTION)]
        assert final_payload(events)["status"] == "success", "".join(events)
        assert [row["id"] for row in avatar.inventory] == ["coat"]
        assert avatar.visual_profile["worn"][0]["item_id"] == "coat"
        assert "AUTHORITATIVE CURRENT APPEARANCE" in str(roles.prompts[-1])
        assert "Blue coat" in str(roles.prompts[-1])
        reply = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == state.session_id, ChatMessage.content == NARRATION
            )
        )
        cue = reply.to_client_dict()["portrait_state"]["npcs"]["LINA"]
        assert cue == {"emotion": "interest", "intensity": 65, "thought": "Let us continue."}
        facts = registry_of(host.state.entity_states)["snapshots"][reply.id]["visible_facts"]
        assert "Blue coat" in json.dumps(facts)
        assert facts["setting"]
        assert len(roles.prompts) == 1
