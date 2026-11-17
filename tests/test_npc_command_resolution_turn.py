"""Real publication keeps an earlier rejected proposal distinct from later facts."""

import json

import pytest

from backend.engine.chpm.state import KEY, load
from backend.engine.npc_actions.control import MESSAGES
from backend.engine.npc_actions.instructions import RESOLUTION_CHRONOLOGY
from tests.conftest import TestSessionLocal
from tests.test_chpm_action_turn import ActionRoles
from tests.test_chpm_host_turn import run
from tests.test_chpm_notebook_turn import ACTION, install
from tests.test_chpm_observable_turn import prepare


class EarlierFailureRoles(ActionRoles):
    def __init__(self):
        super().__init__()
        self.review_payloads = []

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if schema.__name__.startswith("VNProgressionIntent"):
            self.calls.append((schema.__name__, args, kwargs))
            return schema(
                **(
                    {
                        "player_item_actions": [
                            {
                                "operation": "give",
                                "performer_id": "__player__",
                                "item_id": "HIDDEN_RING",
                                "target_id": "LINA",
                                "passage_id": "player:p0",
                                "basis": "performed",
                            }
                        ],
                    }
                    if "player_item_actions" in schema.model_fields
                    else {}
                ),
                updated_entities=[
                    {
                        "entity_id": "LINA",
                        "inventory": [{"name": "Hidden ring", "description": "A ring."}],
                    }
                ],
            )
        return await super().structured(*args, **kwargs)

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") == "validation":
            body = json.loads(payload)
            self.review_payloads.append(body)
            # This double checks the request contract, not a model's interpretation.
            assert RESOLUTION_CHRONOLOGY in system
            assert body["host_resolution_time"] == "before_command_publication"
            assert MESSAGES["preliminary_item_rejected"] in body["host_resolution"]
            outcomes = body["contract"]["LINA"]["authoritative_command_outcomes"]
            assert [item["status"] for item in outcomes] == ["applied", "applied"]
            assert [item["tool"] for item in outcomes] == ["change_item_state", "put_down_item"]
        return await super().simple(system, payload, model, **kwargs)


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_rejected_preliminary_inventory_cannot_erase_later_applied_command_context(
    monkeypatch, protocol
):
    roles = EarlierFailureRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", protocol, False)
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
        manager, events = await run(db, user, ACTION)
        assert any(event.startswith("event: final") for event in events), "".join(events)
        assert not any(event.startswith("event: error") for event in events)
        assert len(roles.review_payloads) == 1
        assert roles.reconciliations[-1]["owners"]["HIDDEN_RING"] == "__scene__"
        assert load(manager.state).actors["LINA"].status == "delivered"
        assert MESSAGES["preliminary_item_rejected"] in str(roles.prompts)
        assert "host_resolution/draft/outcome precedes" in str(roles.prompts)
        assert load(manager.state).usage.calls == 4
