"""An offered coat remains with the actor until an actual handover is published."""

import json

import pytest

from backend.engine.chpm.state import load
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.scene_illustrations.snapshots import REGISTRY_KEY, content_hash
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.npc_sequential_fixture import COAT, owner_state, seed_sequential
from tests.state_response_fixture import extraction
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import install
from tests.test_npc_two_phase_turn import PLAYER, CupRoles, reload

SPEECH = "Лина: «Would you like the coat?»"
GIVEN = "Lina hands the blue coat to her visitor."
OFFERED = "Lina holds out her blue coat and waits for an answer."


class HandoverRoles(CupRoles):
    def __init__(self, accept_repair, *, omit_repeated_transfer=False):
        super().__init__([{"tool": "take_off_item", "item_id": COAT}])
        self.accept_repair = accept_repair
        self.omit_repeated_transfer = omit_repeated_transfer
        self.repairs = []

    @property
    def story(self):
        return f"{SPEECH}\n{GIVEN}"

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") == "repair":
            self.repairs.append(json.loads(payload))
            revised = OFFERED if self.accept_repair else f"{GIVEN} Outside, a bell rings."
            return f"{SPEECH}\n{revised}"
        return await super().simple(system, payload, model, **kwargs)

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if not issubclass(schema, ItemExtraction):
            return await super().structured(*args, **kwargs)
        passages = json.loads(args[1])["completed_narration"]
        transfer = next((key for key, text in passages.items() if text == GIVEN), None)
        actions = (
            [
                {
                    "item_id": COAT,
                    "source_owner": "LINA",
                    "destination_owner": "__player__",
                    "disposition": "held",
                    "basis": "completed",
                    "evidence": transfer,
                }
            ]
            if transfer and not (self.repairs and self.omit_repeated_transfer)
            else []
        )
        return extraction(schema, actions=actions)


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("accept_repair,omit", [(True, False), (False, False), (False, True)])
async def test_unsupported_gift_after_removal_is_corrected_before_visible_output(
    monkeypatch, protocol, accept_repair, omit
):
    roles = HandoverRoles(accept_repair, omit_repeated_transfer=omit)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed_sequential(db, protocol)
        session_id, user_id = state.session_id, user.id
        _, events = await run(db, user, PLAYER)
        output = "".join(
            json.loads(row.partition("\ndata: ")[2])["content"]
            for row in events
            if row.startswith("event: chunk")
        )
    assert len(roles.repairs) == len(roles.executions) == 1
    assert GIVEN not in output
    assert any(row.startswith("event: final") for row in events) is accept_repair
    async with TestSessionLocal() as db:
        _, host, _ = await reload(db, session_id, user_id)
        assert await owner_state(host) == ("LINA", set() if accept_repair else {COAT})
        if accept_repair:
            decision = load(host.state).actors["LINA"]
            assert [(row.tool, row.status) for row in decision.last_publication.operations] == [
                ("take_off_item", "applied")
            ]
            reply = await db.get(ChatMessage, decision.reply_id)
            snapshot = host.state.entity_states[REGISTRY_KEY]["snapshots"][reply.id]
            assert output == reply.content == snapshot["narration"] == f"{SPEECH}\n{OFFERED}"
            assert snapshot["content_hash"] == content_hash(reply)
        else:
            assert not output
            assert not load(host.state).actors
            assert not host.state.entity_states.get(REGISTRY_KEY, {}).get("snapshots")
