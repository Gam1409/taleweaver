"""Approved tools affect real owners before narration and survive reload through both ports."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.engine.chpm import continuation
from backend.engine.chpm.runtime import Turn
from backend.engine.chpm.schema import KernelState
from backend.engine.chpm.state import KEY, load
from backend.engine.physical_conditions.ledger import read
from backend.engine.turn_replay.snapshot import capture, restore
from tests.conftest import TestSessionLocal
from tests.npc_control_support import bind_turn
from tests.test_chpm_host_turn import run
from tests.test_chpm_native_notebook_loop import call, turn
from tests.test_chpm_native_notebook_turn import initial_payload, tool_results
from tests.test_chpm_notebook_turn import ACTION, install
from tests.test_chpm_observable_turn import DETAIL, StateRoles, prepare

STATE = "The ring is now polished."


def test_fallback_keeps_applied_world_effects_after_abandoning_psychological_proposals():
    current = Turn(KernelState(), "input")
    current.action_outcomes = {
        "NPC": [
            {
                "index": 0,
                "tool": "put_down_item",
                "status": "applied",
                "effect": {"item_id": "KEY", "destination_owner": "__scene__"},
            }
        ]
    }
    bind_turn(SimpleNamespace(game_id="session", _vn_player_message_id="input"), current)
    continuation.activate(current, "review_unavailable")
    content = continuation.contract(current)
    assert "authoritative_command_outcomes" in content and "KEY" in content
    assert "before_command_publication" in content
    assert current.decisions == {}


class ActionRoles(StateRoles):
    @staticmethod
    def commands():
        return [
            {
                "name": "change_item_state",
                "arguments": {"item_id": "HIDDEN_RING", "dimension": "surface", "detail": STATE},
            },
            {
                "name": "put_down_item",
                "arguments": {"item_id": "HIDDEN_RING", "position": "on the bench"},
            },
        ]

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") != "integrated_decision":
            return await super().simple(system, payload, model, **kwargs)
        self.chpm_calls.append(kwargs["phase"])
        body = json.loads(payload)
        self.lookups.append(body)
        requests = (
            self.commands()
            if not body["previous_lookups"]
            else [{"name": "submit_decision", "arguments": await self.decision(body, model)}]
        )
        return json.dumps({"requests": requests})

    async def native(self, messages, tools, model, **kwargs):
        self.chpm_calls.append(kwargs["phase"])
        body = initial_payload(messages)
        self.lookups.append(body)
        requests = (
            self.commands()
            if not tool_results(messages)
            else [{"name": "submit_decision", "arguments": await self.decision(body, model)}]
        )
        return turn(
            *(
                call(f"action-{len(tool_results(messages))}-{index}", row["name"], row["arguments"])
                for index, row in enumerate(requests)
            )
        )


class PausedNarrator(ActionRoles):
    def __init__(self):
        super().__init__()
        self.paused = asyncio.Event()

    async def stream(self, *args, **kwargs):
        self.paused.set()
        await asyncio.Event().wait()


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_commands_reach_owners_narrator_shared_extractor_and_recoverable_storage(
    monkeypatch, protocol
):
    roles = ActionRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", protocol, False)
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
        before = await capture(db, state.session_id)
        manager, chunks = await run(db, user, ACTION)
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        assert not any(chunk.startswith("event: error") for chunk in chunks)
        await db.refresh(state)
        conditions = read(state.entity_states).conditions.values()
        assert any(row.part == "damage" and row.detail == DETAIL for row in conditions)
        assert any(
            row.part == "surface" and row.detail == STATE and row.latest.kind == "command"
            for row in conditions
        )
        assert roles.reconciliations[-1]["owners"]["HIDDEN_RING"] == "__scene__"
        assert (
            roles.reconciliations[-1]["items"]["HIDDEN_RING"]["spatial_position"] == "on the bench"
        )
        prompt = str(roles.prompts)
        assert "authoritative_command_outcomes" in prompt and STATE in prompt
        assert "before_command_publication" in prompt
        assert load(state).usage.calls == 4
        await restore(db, state.session_id, before)
        await db.commit()
        await db.refresh(state)
        assert not any(
            row.part == "surface" for row in read(state.entity_states).conditions.values()
        )


async def test_cancellation_after_command_publication_preserves_a_recoverable_turn(monkeypatch):
    roles = PausedNarrator()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", "json", False)
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
        before = read(state.entity_states)
        before_kernel = load(state)
        task = asyncio.create_task(run(db, user, ACTION))
        await asyncio.wait_for(roles.paused.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await db.refresh(state)
        assert read(state.entity_states) == before
        assert load(state) == before_kernel
