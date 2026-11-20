"""The full turn must defer an NPC acquisition until its own action owner decides."""

import pytest

from backend.engine.chpm.state import KEY, load
from backend.engine.npc_actions.control import MESSAGES
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_notebook_turn import install
from tests.test_chpm_observable_turn import prepare
from tests.test_vn_preliminary_item_resolution import PreliminaryKeyFailureRoles
from tests.test_vn_turn_integration import final_payload


class PendingAcquisitionRoles(PreliminaryKeyFailureRoles):
    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if not schema.__name__.startswith("VNProgressionIntent"):
            return await super().structured(*args, **kwargs)
        self.calls.append((schema.__name__, args, kwargs))
        # This is the formerly accepted-looking, but unauthorized, preliminary claim.
        return schema(
            narrative_description="Lina has already taken the brass key.",
            player_item_actions=[
                {
                    "operation": "take",
                    "performer_id": "LINA",
                    "item_id": "BRASS_KEY",
                    "passage_id": "player:p0",
                    "basis": "performed",
                }
            ],
            updated_entities=[
                {
                    "entity_id": "LINA",
                    "inventory": [{"id": "BRASS_KEY", "name": "Brass key"}],
                    "movement_source": {
                        "kind": "current_player_action",
                        "passage_id": "player:p0",
                        "basis": "resolved_external_effect",
                    },
                }
            ],
        )


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_npc_takes_then_gives_the_real_item_after_a_preliminary_acquisition_claim(
    monkeypatch, protocol
):
    roles = PendingAcquisitionRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", protocol, False)
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        db.add(
            WorldEntity(
                id="BRASS_KEY",
                session_id=state.session_id,
                entity_type="OBJECT",
                name="Brass key",
                description="One ordinary brass key.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
            )
        )
        await db.commit()
        manager, events = await run(db, user, "Lina, take the brass key and give it to me.")
        assert final_payload(events)["status"] == "success", "".join(events)
        reviewed = roles.review_payloads[0]
        outcomes = reviewed["contract"]["LINA"]["authoritative_command_outcomes"]
        assert [row["tool"] for row in outcomes] == ["take_item", "give_item"]
        assert [row["status"] for row in outcomes] == ["applied", "applied"]
        assert len({row["operation_id"] for row in outcomes}) == 2
        assert MESSAGES["preliminary_item_deferred"] in reviewed["host_resolution"]
        assert "Lina has already taken" not in reviewed["host_resolution"]
        assert manager._vn_item_rejection is None
        assert roles.reconciliations[-1]["owners"]["BRASS_KEY"] == "__player__"
        assert load(manager.state).usage.calls == 4
        await db.refresh(manager.avatar)
        assert [row["id"] for row in manager.avatar.inventory].count("BRASS_KEY") == 1
