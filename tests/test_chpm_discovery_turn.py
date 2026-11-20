"""Discovery results feed exact-ID reads through both tool ports and real turn publication."""

import json

import pytest

from backend.engine.chpm.state import load
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_native_notebook_loop import call, turn
from tests.test_chpm_native_notebook_turn import initial_payload, tool_results
from tests.test_chpm_notebook_turn import ACTION, install
from tests.test_chpm_observable_turn import DETAIL, StateRoles, prepare


class DiscoveryRoles(StateRoles):
    @staticmethod
    def requests(previous):
        if not previous:
            return [
                {"name": "find_entity", "arguments": {"argument": "Hidden ring"}},
                {"name": "inspect_scene", "arguments": {}},
            ]
        if len(previous) == 1:
            identifier = previous[0]["results"][0]["results"][0]["id"]
            return [{"name": "inspect_entity", "arguments": {"argument": identifier}}]
        return []

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") != "integrated_decision":
            return await super().simple(system, payload, model, **kwargs)
        self.chpm_calls.append(kwargs["phase"])
        body = json.loads(payload)
        self.lookups.append(body)
        requests = self.requests(body["previous_lookups"])
        if not requests:
            requests = [{"name": "submit_decision", "arguments": await self.decision(body, model)}]
        return json.dumps({"requests": requests})

    async def native(self, messages, tools, model, **kwargs):
        self.chpm_calls.append(kwargs["phase"])
        body = initial_payload(messages)
        self.lookups.append(body)
        previous = tool_results(messages)
        if not previous:
            requests = self.requests([])
        elif len(previous) == 2:
            requests = [
                {
                    "name": "inspect_entity",
                    "arguments": {"argument": previous[0]["results"][0]["id"]},
                }
            ]
        else:
            requests = [{"name": "submit_decision", "arguments": await self.decision(body, model)}]
        return turn(
            *(
                call(f"read-{len(previous)}-{index}", row["name"], row["arguments"])
                for index, row in enumerate(requests)
            )
        )


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_discovery_and_room_state_reach_the_real_decision_and_narrator(monkeypatch, protocol):
    roles = DiscoveryRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _ = await prepare(db, "integrated", protocol, False)
        manager, chunks = await run(db, user, ACTION)
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        saved = load(manager.state)
        assert [
            row["tool"] for step in saved.actors["LINA"].agent_audit for row in step["requests"]
        ] == ["find_entity", "inspect_scene", "inspect_entity"]
        evidence = saved.actors["LINA"].agent_evidence
        assert any(DETAIL in row.text for row in evidence)
        scene = next(
            json.loads(row.text) for row in evidence if "current_observable_scene" in row.text
        )
        assert scene["scene_id"] == manager.state.current_scene_id
        assert {row["id"] for row in scene["visible_actors"]} == {"LINA", "@player"}
        assert "current_observable_scene" in str(roles.prompts)
        assert saved.usage.calls == 5
