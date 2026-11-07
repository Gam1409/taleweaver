"""Saved VN replies, replay and failure paths share the existing model request."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.debug_engine import DebugEngine
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.ledger import read
from backend.engine.physical_conditions.schema import KEY
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_physical_conditions import record
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn

NARRATION = 'Лина перевязала рану на шее. Лина: "Идём дальше."'
PROPOSAL = record(
    target_id="LINA",
    evidence="Лина перевязала рану на шее.",
    detail="A bandaged neck wound.",
    visibility="public",
)


class ConditionRoles(TurnRoles):
    proposals = [PROPOSAL]
    fail = False

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if schema is ItemExtraction:
            self.calls.append((schema.__name__, args, kwargs))
            if self.fail:
                raise TimeoutError("Simulated shared extraction failure")
            return ItemExtraction(condition_updates=self.proposals)
        return await super().structured(*args, **kwargs)


@pytest.mark.asyncio
async def test_saved_reply_anchors_condition_and_next_turn_gets_fact_without_extra_call(
    monkeypatch,
):
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", NARRATION)
    roles = ConditionRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        before_inventory = deepcopy(avatar.inventory)
        manager = GameTurnManager(db, "session-1", user)
        events = [event async for event in manager.process_turn("Помочь Лине.")]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        condition = next(iter(read(state.entity_states).conditions.values()))
        reply = await db.get(ChatMessage, condition.origin.message_id)
        assert reply and reply.role == "assistant" and reply.content == NARRATION
        assert condition.origin.quote in reply.content
        assert condition.status == "active" and avatar.inventory == before_inventory
        assert len(roles.calls) == 3 and len(roles.prompts) == 1
        extraction = next(call for call in roles.calls if call[0] == "ItemExtraction")
        assert "PHYSICAL CONDITIONS" in extraction[1][0]
        state_id, saved = state.id, condition.model_dump()
        roles.proposals = []
    async with TestSessionLocal() as db:
        events = [
            event async for event in GameTurnManager(db, "session-1", user).process_turn("Идём.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        state = await db.get(SessionState, state_id)
        assert read(state.entity_states).conditions[condition.id].model_dump() == saved
        assert len(roles.calls) == 6
        assert "A bandaged neck wound." in json.dumps(
            roles.prompts[-1], ensure_ascii=False, default=str
        )
        progression = [call for call in roles.calls if call[0].startswith("VNProgressionIntent")][
            -1
        ]
        assert "A bandaged neck wound." in progression[1][1]


@pytest.mark.asyncio
async def test_full_turn_replay_rewinds_conditions_and_old_message_anchor(monkeypatch):
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", NARRATION)
    roles = ConditionRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        events = [
            event async for event in GameTurnManager(db, "session-1", user).process_turn("Идём.")
        ]
        assert final_payload(events)["status"] == "success"
        condition = next(iter(read(state.entity_states).conditions.values()))
        roles.proposals = []
        retry = GameTurnManager(db, "session-1", user)
        events = [
            event
            async for event in retry.process_turn(
                "ignored", replay_message_id=condition.origin.message_id
            )
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        assert not read(state.entity_states).conditions
        assert await db.get(ChatMessage, condition.origin.message_id) is None
        assert "A bandaged neck wound." not in json.dumps(roles.prompts[-1], default=str)


@pytest.mark.asyncio
async def test_shared_timeout_keeps_existing_state_and_publishes_reply(monkeypatch):
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", NARRATION)
    roles = ConditionRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        first = [
            event async for event in GameTurnManager(db, "session-1", user).process_turn("Идём.")
        ]
        assert final_payload(first)["status"] == "success"
        original = read(state.entity_states).conditions
        roles.fail = True
        events = [
            event async for event in GameTurnManager(db, "session-1", user).process_turn("Дальше.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        ledger = read(state.entity_states)
        assert ledger.conditions == original and ledger.last_check["status"] == "failed"
        assert await db.scalar(
            select(ChatMessage.id).where(ChatMessage.id == ledger.last_check["message_id"])
        )


@pytest.mark.asyncio
async def test_manual_correction_is_scoped_revision_checked_and_does_not_advance_world():
    async with TestSessionLocal() as db:
        _, avatar, state, _ = await seed_vn(db)
        before = deepcopy(state.entity_states)
        command = "condition " + json.dumps({**PROPOSAL, "expected_revision": 0})
        assert "Enable debug mode" in await DebugEngine.handle_debug_command(db, state, command)
        assert state.entity_states == before
        state.is_debug_enabled = True
        clock, inventory = state.in_game_time, deepcopy(avatar.inventory)
        bad = "condition " + json.dumps(
            {**PROPOSAL, "target_id": "FOREIGN", "expected_revision": 0}
        )
        assert (await DebugEngine.handle_debug_command(db, state, bad)).startswith("DEBUG ERROR")
        assert state.entity_states == before
        assert (await DebugEngine.handle_debug_command(db, state, command)).startswith(
            "DEBUG: Updated"
        )
        ledger = read(state.entity_states)
        condition = next(iter(ledger.conditions.values()))
        assert condition.origin.kind == "manual" and condition.origin.message_id is None
        assert "Refresh" in await DebugEngine.handle_debug_command(db, state, command)
        heal = "condition " + json.dumps(
            {"operation": "heal", "condition_id": condition.id, "expected_revision": 1}
        )
        assert (await DebugEngine.handle_debug_command(db, state, heal)).startswith(
            "DEBUG: Updated"
        )
        assert read(state.entity_states).conditions[condition.id].status == "resolved"
        assert state.in_game_time == clock and avatar.inventory == inventory
        assert {k: v for k, v in state.entity_states.items() if k != KEY} == before


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_condition", [True, False])
async def test_item_and_condition_candidates_are_independently_applied(monkeypatch, bad_condition):
    from backend.engine.narrated_items.schema import ItemAction

    narration = "Лина перевязала рану на шее. Лина передала герою шарф, и он убрал его в сумку."
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", narration)

    class MixedRoles(ConditionRoles):
        async def structured(self, *args, **kwargs):
            schema = kwargs.get("response_model") or args[2]
            if schema is not ItemExtraction:
                return await super().structured(*args, **kwargs)
            self.calls.append((schema.__name__, args, kwargs))
            identity = (
                {
                    "new_item": {
                        "name": "Шарф",
                        "description": "Синий шерстяной шарф с узкими кисточками.",
                        "kind": "ordinary",
                    }
                }
                if bad_condition
                else {"item_id": "UNKNOWN"}
            )
            return ItemExtraction(
                actions=[
                    ItemAction(
                        **identity,
                        source_owner="LINA",
                        destination_owner="__player__",
                        disposition="carried",
                        evidence="Лина передала герою шарф, и он убрал его в сумку.",
                        basis="completed",
                    )
                ],
                condition_updates=[{"operation": "broken"}] if bad_condition else [PROPOSAL],
            )

    roles = MixedRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        events = [
            event async for event in GameTurnManager(db, "session-1", user).process_turn("Идём.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        await db.refresh(avatar)
        assert bool(read(state.entity_states).conditions) != bad_condition
        assert any(item.get("name") == "Шарф" for item in avatar.inventory) == bad_condition
        assert any(event.startswith("event: system") and "review" in event for event in events)
        assert len(roles.calls) == 3


@pytest.mark.asyncio
async def test_live_chpm_receives_own_private_body_state_without_extra_phase(monkeypatch):
    from backend.engine.chpm import inference, rendering
    from backend.engine.chpm.schema import KernelState, Settings
    from backend.engine.chpm.state import KEY as CHPM_KEY
    from backend.engine.physical_conditions.ledger import apply
    from tests.test_chpm_turn import ChpmRoles

    roles = ChpmRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        message = ChatMessage(
            session_id="session-1", role="assistant", content="Lina has a neck wound."
        )
        db.add(message)
        await db.flush()
        state.entity_states, _, errors = apply(
            state.entity_states,
            [record(target_id="LINA", evidence=message.content, detail="PRIVATE_BODY_FACT")],
            targets={"LINA"},
            narration=message.content,
            message_id=message.id,
            session_id="session-1",
            minute=0,
        )
        assert not errors
        state.entity_states = {
            **state.entity_states,
            CHPM_KEY: KernelState(
                settings=Settings(mode="live", actor_ids=["LINA"], failure_policy="strict")
            ).model_dump(),
        }
        await db.commit()
        events = [
            event
            async for event in GameTurnManager(db, "session-1", user).process_turn("Что дальше?")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        supplied = roles.proposal_inputs[0]
        frame = supplied["psychological_state"]["current_host_observations"][0]
        facts = json.loads(frame["text"])["physical_conditions"]
        assert facts[0]["detail"] == "PRIVATE_BODY_FACT"
        assert "own_physical_conditions" not in supplied
        assert roles.chpm_calls == ["perception", "proposal", "validation"]
        assert "PRIVATE_BODY_FACT" not in json.dumps(roles.prompts, ensure_ascii=False, default=str)


@pytest.mark.asyncio
async def test_visible_loose_item_condition_reaches_both_continuity_and_narrator(monkeypatch):
    from backend.engine.physical_conditions.ledger import apply
    from backend.models.world_entity import WorldEntity

    roles = TurnRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        db.add(
            WorldEntity(
                id="VASE",
                session_id="session-1",
                entity_type="OBJECT",
                name="Vase",
                description="A ceramic vase.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
                is_portable=True,
            )
        )
        message = ChatMessage(
            session_id="session-1", role="assistant", content="The vase is cracked."
        )
        db.add(message)
        await db.flush()
        state.entity_states, _, errors = apply(
            state.entity_states,
            [
                record(
                    target_id="VASE",
                    kind="other",
                    part="ceramic",
                    detail="PUBLIC_CRACK",
                    visibility="public",
                    evidence=message.content,
                )
            ],
            targets={"VASE"},
            narration=message.content,
            message_id=message.id,
            session_id="session-1",
            minute=0,
        )
        assert not errors
        await db.commit()
        events = [
            event
            async for event in GameTurnManager(db, "session-1", user).process_turn(
                "Я смотрю на вазу."
            )
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        assert "PUBLIC_CRACK" in json.dumps(roles.prompts, ensure_ascii=False, default=str)
        progression = next(
            call for call in roles.calls if call[0].startswith("VNProgressionIntent")
        )
        assert "PUBLIC_CRACK" in progression[1][1]
        assert len(roles.calls) == 3
