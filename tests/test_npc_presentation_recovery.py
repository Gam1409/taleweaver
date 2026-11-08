"""Portrait data belongs to the published reply even during Personality recovery."""

import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.core.npc_presentation import source_hash
from backend.engine.chpm import continuation_writer, inference, rendering
from backend.engine.chpm.recovery_contracts import RecoveryState
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.npc_presentation.settings import KEY as PORTRAIT_KEY
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import ACTION, install_roles, seed_vn


def metadata(emotion, thought):
    return (
        "<npc-state>"
        + json.dumps(
            {
                "npcs": [
                    {
                        "npc_id": "LINA",
                        "emotion": emotion,
                        "intensity": 70,
                        "thought": thought,
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "</npc-state>"
    )


@pytest.mark.parametrize("recovery", ["cooldown", "replacement"])
async def test_recovery_keeps_preferences_and_publishes_only_its_own_portrait_data(
    monkeypatch, recovery
):
    thought = "Теперь можно спокойно поговорить."

    class Roles(ChpmRoles):
        async def simple(self, system, payload, model, **kwargs):
            if kwargs.get("phase") == "rp_continuation":
                self.chpm_calls.append("rp_continuation")
                data = json.loads(payload)
                assert "private footer" in data["portrait_output"]
                assert "English" in data["portrait_output"]
                return "Лина: «Давай продолжим разговор»." + metadata("trust", thought)
            return await super().simple(system, payload, model, **kwargs)

        async def stream(self, *args, **kwargs):
            original = await super().stream(*args, **kwargs)

            async def chunks():
                async for chunk in original:
                    yield chunk
                emotion = "interest" if recovery == "cooldown" else "anger"
                text = thought if recovery == "cooldown" else "REJECTED_THOUGHT"
                yield MagicMock(
                    choices=[
                        MagicMock(
                            delta=MagicMock(content=metadata(emotion, text)), finish_reason="stop"
                        )
                    ]
                )

            return chunks()

    roles = Roles(reject=recovery == "replacement")
    install_roles(monkeypatch, roles)
    for module in (inference, rendering, continuation_writer):
        monkeypatch.setattr(module, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        settings = Settings(mode="live", actor_ids=["LINA"])
        kernel = KernelState(settings=settings)
        if recovery == "cooldown":
            kernel.recovery = RecoveryState(cooldown_remaining=1, consecutive_failures=2)
        state.entity_states = {
            **state.entity_states,
            KEY: kernel.model_dump(),
            PORTRAIT_KEY: {
                "emotion_palette": True,
                "character_thoughts": True,
            },
        }
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        events = [event async for event in manager.process_turn(ACTION)]
        assert any(event.startswith("event: final") for event in events), "".join(events)
        saved = load(manager.state)
        assert saved.settings == settings
        assert saved.usage.simplified
        assert saved.usage.fallback_reason == (
            "cooldown" if recovery == "cooldown" else "review_rejected"
        )
        assert manager.state.entity_states[PORTRAIT_KEY]["emotion_palette"]
        assert manager.state.entity_states[PORTRAIT_KEY]["character_thoughts"]
        replies = list(
            await db.scalars(select(ChatMessage).where(ChatMessage.portrait_state.is_not(None)))
        )
        assert len(replies) == 1
        reply = replies[0]
        cues = reply.to_client_dict()["portrait_state"]
        assert cues["source_hash"] == source_hash(reply.content)
        assert cues["npcs"]["LINA"] == {
            "emotion": "interest" if recovery == "cooldown" else "trust",
            "intensity": 70,
            "thought": thought,
        }
        assert "REJECTED_THOUGHT" not in "".join(events)
        assert "<npc-state>" not in "".join(events)
        assert len(roles.prompts) == 1
        assert roles.chpm_calls.count("rp_continuation") == int(recovery == "replacement")
