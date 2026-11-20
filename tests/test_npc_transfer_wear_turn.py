"""A public clothing transfer cannot invent a separate receiving actor's wear action."""

import json

import pytest
from sqlalchemy import select

from backend.engine.chpm.state import load
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.visuals import session_objects
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.visual_novel.continuity import PLAYER as PLAYER_OWNER
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import install
from tests.test_clothing_runtime import item, profile
from tests.test_npc_reviewed_custody_turn import SPEECH
from tests.test_npc_two_phase_turn import PLAYER, CupRoles, reload, seed

COAT = "BLUE_COAT"
TRANSFER = "Лина снимает пальто и передает его путешественнику."
EXTRA = "Путешественник надевает полученное пальто."
STILL_EXTRA = "Путешественник уже одет в полученное пальто."


class TransferWearRoles(CupRoles):
    def __init__(self, corrected):
        super().__init__(
            [
                {"tool": "take_off_item", "item_id": COAT},
                {"tool": "give_item", "item_id": COAT, "recipient_id": "@player"},
            ]
        )
        self.corrected = corrected
        self.repairs = []
        self.extracted = []

    @property
    def story(self):
        return f"{SPEECH}\n{TRANSFER}\n{EXTRA}"

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") == "repair":
            self.repairs.append(json.loads(payload))
            return f"{SPEECH}\n{TRANSFER}" + ("" if self.corrected else f"\n{STILL_EXTRA}")
        return await super().simple(system, payload, model, **kwargs)

    def review(self, supplied):
        result = json.loads(super().review(supplied))
        result["completed_changes"] = []
        return json.dumps(result)

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if not issubclass(schema, ItemExtraction):
            return await super().structured(*args, **kwargs)
        passages = json.loads(args[1])["completed_narration"]
        unsupported = any(line in {EXTRA, STILL_EXTRA} for line in passages.values())
        target = next(
            key
            for key, line in passages.items()
            if line in ({EXTRA, STILL_EXTRA} if unsupported else {TRANSFER})
        )
        self.extracted.append(unsupported)
        return extraction(
            schema,
            actions=[
                {
                    "item_id": COAT,
                    "source_owner": "LINA",
                    "destination_owner": PLAYER_OWNER,
                    "disposition": "worn" if unsupported else "carried",
                    "basis": "completed",
                    "evidence": target,
                }
            ],
        )


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("corrected", [False, True])
async def test_transfer_wear_extra_is_repaired_or_rolled_back_before_publication(
    monkeypatch, protocol, corrected
):
    roles = TransferWearRoles(corrected)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed(db, protocol, pair=False)
        user_id, session_id = user.id, state.session_id
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        npc.inventory, npc.visual_profile = [item(COAT)], profile(COAT)
        await db.commit()

        _, events = await run(db, user, PLAYER)

        assert len(roles.choices) == len(roles.executions) == len(roles.repairs) == 1
        assert len(roles.reviews) == 2 and roles.extracted == [True, not corrected]
        (failure,) = roles.repairs[0]["completed_change_rejections"]["rejections"]
        assert failure["reason_code"] == "custody_placement_mismatch"
        assert failure["expected_public_result"]["destination_owner"] == "@player"
        chunks = [
            json.loads(row.partition("\ndata: ")[2])["content"]
            for row in events
            if row.startswith("event: chunk")
        ]
        assert chunks == ([f"{SPEECH}\n{TRANSFER}"] if corrected else [])
        assert any(row.startswith("event: final") for row in events) == corrected

    async with TestSessionLocal() as db:
        _, manager, snapshot = await reload(db, session_id, user_id)
        assert snapshot.owners[COAT] == (PLAYER_OWNER if corrected else "LINA")
        actors = actor_records(manager, await session_objects(db, session_id))
        worn = load_profile(actors["LINA"]["visual_profile"]).worn
        assert (COAT in {entry.item_id for entry in worn}) != corrected
        saved = list(
            await db.scalars(
                select(ChatMessage.content).where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.content.contains(SPEECH),
                )
            )
        )
        assert saved == chunks
        if not corrected:
            assert not load(manager.state).actors
