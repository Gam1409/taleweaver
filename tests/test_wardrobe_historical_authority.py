"""Completed prose cannot replay a source-time command-owned wardrobe change."""

import json
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.engine.chpm.state import KEY, load
from backend.engine.clothing import runtime as clothing_runtime
from backend.engine.clothing.profiles import load_profile
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.runtime import KEY as ITEMS
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.npc_actions import publication
from backend.engine.npc_actions.control import CommandRejectedError
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.chpm_reference_fixture import proposal as reference_proposal
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_chpm_host_turn import run
from tests.test_chpm_kernel import motivated_candidates, preferred_choice
from tests.test_chpm_notebook_turn import ACTION, install
from tests.test_chpm_observable_turn import prepare
from tests.test_clothing_runtime import action, item, profile
from tests.test_npc_action_empty_turn import EmptyPlanRoles
from tests.test_vn_turn_integration import NARRATION, final_payload

NARRATED_CHANGE = "Lina raises the sleeves of her coat."


class HistoricalRoles(EmptyPlanRoles):
    def __init__(self, outcome):
        super().__init__()
        self.outcome, self.recover = outcome, False
        self.staged = False

    async def decision(self, body, _model):
        self.proposal_inputs.append(body)
        return reference_proposal(
            {
                "new_beliefs": [],
                "belief_revisions": [],
                "choice": preferred_choice(body),
                "candidates": motivated_candidates(
                    {
                        "CONTINUE": {
                            "intention": "Continue the discussion and consider a practical next step.",
                            "goal_alignment": "supports",
                            "goal_quote": body["authored_goal"],
                            "reconsider_if": "The discussion ends.",
                        },
                        "DEFER": {
                            "intention": "Remain silent.",
                            "goal_alignment": "unknown",
                            "goal_quote": "",
                            "reconsider_if": "A new request arrives.",
                        },
                    }
                ),
            },
            body,
        )

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if issubclass(schema, ItemExtraction):
            actions = (
                []
                if self.recover
                else [
                    {
                        "item_id": "coat",
                        "source_owner": "LINA",
                        "destination_owner": "LINA",
                        "disposition": "worn",
                        "uncovered_regions": ["arms"],
                        "basis": "completed",
                        "evidence": NARRATED_CHANGE,
                    }
                ]
            )
            return extraction(schema, actions=actions)
        result = await super().structured(*args, **kwargs)
        if self.recover and schema.__name__.startswith("VNProgressionIntent"):
            result.wardrobe_actions = [
                action(
                    actor_id="LINA",
                    source="completed_narration",
                    evidence=NARRATED_CHANGE,
                    operation="adjust",
                    uncovered_regions=["arms"],
                    agency="npc_choice",
                )
            ]
        return result

    async def simple(self, system, payload, model, **kwargs):
        phase = kwargs.get("phase")
        supplied = json.loads(payload)
        if phase == "validation" and not self.recover:
            self.chpm_calls.append(phase)
            return json.dumps(
                {
                    "review_scope": supplied["review_scope"],
                    "matches": True,
                    "actions": [{"actor_id": "LINA", "passage_id": "p0"}],
                }
            )
        if phase == "integrated_decision" and self.outcome != "empty" and not self.recover:
            self.chpm_calls.append(phase)
            request = (
                {"name": "submit_decision", "arguments": await self.decision(supplied, model)}
                if self.staged
                else {
                    "name": "adjust_clothing",
                    "arguments": {"item_id": "coat", "uncovered_regions": ["arms"]},
                }
            )
            self.staged = True
            return json.dumps({"requests": [request]})
        return await super().simple(system, payload, model, **kwargs)

    async def stream(self, *args, **kwargs):
        self.prompts.append((args, kwargs))
        text = NARRATION if self.recover else NARRATED_CHANGE

        async def chunks():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=text))])

        return chunks()


@pytest.mark.parametrize("outcome", ["empty", "rejected", "applied"])
@pytest.mark.parametrize("current_mode", ["live", "off"])
async def test_saved_command_control_prevents_next_turn_wardrobe_replay(
    monkeypatch, outcome, current_mode
):
    roles = HistoricalRoles(outcome)
    install(monkeypatch, roles)
    fresh = publication._fresh

    async def owner_check(manager, scope):
        if outcome == "rejected" and not roles.recover:
            raise CommandRejectedError("unavailable_entity")
        return await fresh(manager, scope)

    monkeypatch.setattr(publication, "_fresh", owner_check)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", "json", False)
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        npc.inventory, npc.visual_profile = [*npc.inventory, item()], profile("coat")
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
        manager, events = await run(db, user, ACTION)
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        current = state.entity_states.get("LINA", {}).get("visual_profile", npc.visual_profile)
        if outcome == "applied":
            worn = load_profile(current).worn[0]
            assert worn.uncovered_regions == ["arms"] and worn.source.source_role == "command"
            assert not state.entity_states[ITEMS]["rejected"]
        else:
            assert (
                load_profile(current).model_dump() == load_profile(npc.visual_profile).model_dump()
            )
            assert state.entity_states[ITEMS]["rejected"]
        expected = deepcopy(load_profile(current).model_dump())
        reply_id = load(state).actors["LINA"].reply_id
        state_id, user_id = state.id, user.id
    roles.recover = True

    def unexpected_mutation(*_args, **_kwargs):
        raise AssertionError("Historical command-owned text must not mutate canonical wear.")

    monkeypatch.setattr(clothing_runtime, "change_owned_wear", unexpected_mutation)
    async with TestSessionLocal() as db:
        state, user = await db.get(SessionState, state_id), await db.get(User, user_id)
        kernel = load(state)
        kernel.settings.mode = current_mode
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
        manager = GameTurnManager(db, state.session_id, user)
        events = [event async for event in manager.process_turn("I study the map.")]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        current = state.entity_states.get("LINA", {}).get("visual_profile", npc.visual_profile)
        assert load_profile(current).model_dump() == expected
        reply = await db.get(ChatMessage, reply_id)
        assert reply.npc_recovery["command_controlled_actor_ids"] == ["LINA"]
        assert reply.npc_recovery["actors"] == {}
