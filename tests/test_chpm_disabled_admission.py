"""Disabled Personality preserves unused ledgers without admitting them into a turn."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.engine.chpm import inference, runtime
from backend.engine.chpm.state import KEY
from tests.test_chpm_runtime import manager


@pytest.mark.parametrize("version", [1, 6])
@pytest.mark.parametrize("mode", ["off", "shadow", "live"])
async def test_off_checks_settings_but_does_not_validate_or_use_an_invalid_saved_mind(
    monkeypatch, mode, version
):
    host, actor = manager(mode)
    host.state.entity_states[KEY]["schema_version"] = version
    host.state.entity_states[KEY]["minds"] = {"npc": {"invalid": "unused saved data"}}
    before = deepcopy(host.state.entity_states)
    request = AsyncMock(side_effect=AssertionError("No request before admission"))
    monkeypatch.setattr(inference, "request", request)
    if mode == "off":
        assert await runtime.prepare(host, "Hello", [actor]) == ""
        assert not runtime.buffered(host)
        assert not hasattr(host, "_chpm_turn")
    else:
        with pytest.raises(ValidationError):
            await runtime.prepare(host, "Hello", [actor])
    request.assert_not_awaited()
    assert host.state.entity_states == before


async def test_real_off_turn_keeps_portrait_features_without_loading_an_unused_invalid_mind(
    monkeypatch,
):
    from unittest.mock import MagicMock

    from sqlalchemy import select

    from backend.engine.chpm.schema import KernelState, Settings
    from backend.engine.gameplay.manager import GameTurnManager
    from backend.engine.npc_presentation.settings import KEY as PORTRAIT_KEY
    from backend.models.chat import ChatMessage
    from tests.conftest import TestSessionLocal
    from tests.test_vn_turn_integration import (
        NARRATION,
        TurnRoles,
        final_payload,
        install_roles,
        seed_vn,
    )

    class Roles(TurnRoles):
        async def stream(self, *args, **kwargs):
            original = await super().stream(*args, **kwargs)

            async def chunks():
                async for chunk in original:
                    yield chunk
                footer = '<npc-state>{"npcs":[{"npc_id":"LINA","emotion":"interest","intensity":65,"thought":"I want to hear the next step."}]}</npc-state>'
                yield MagicMock(choices=[MagicMock(delta=MagicMock(content=footer))])

            return chunks()

    roles = Roles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        raw = KernelState(settings=Settings(mode="off", actor_ids=["LINA"])).model_dump()
        raw["minds"] = {"LINA": {"invalid": "unused saved data"}}
        state.entity_states = {
            **state.entity_states,
            KEY: raw,
            PORTRAIT_KEY: {"emotion_palette": True, "character_thoughts": True},
        }
        await db.commit()
        before = deepcopy(raw)
        host = GameTurnManager(db, state.session_id, user)
        events = [chunk async for chunk in host.process_turn("Continue.")]
        assert final_payload(events)["status"] == "success", "".join(events)
        reply = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == state.session_id, ChatMessage.content == NARRATION
            )
        )
        assert reply.to_client_dict()["portrait_state"]["npcs"]["LINA"] == {
            "emotion": "interest",
            "intensity": 65,
            "thought": "I want to hear the next step.",
        }
        assert host.state.entity_states[KEY] == before
        assert len(roles.prompts) == 1


@pytest.mark.parametrize("invalid", ["settings", "version"])
async def test_off_does_not_bypass_unknown_envelopes_or_invalid_settings(invalid):
    host, actor = manager("off")
    if invalid == "settings":
        host.state.entity_states[KEY]["settings"]["max_calls_per_turn"] = -1
    else:
        host.state.entity_states[KEY]["schema_version"] = 999
    before = deepcopy(host.state.entity_states)
    with pytest.raises(ValidationError):
        await runtime.prepare(host, "Hello", [actor])
    assert host.state.entity_states == before
