"""Completed RP updates survive save/reload/scene changes independently of personality."""

from copy import deepcopy

from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.clothing.wear_provenance import remap_profile
from backend.engine.narrated_items.context import actor_context
from backend.engine.narrated_items.schema import ItemAction, ItemExtraction
from backend.engine.npc_cards.current_state import character_current_state
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_narrated_items import fixtures
from tests.test_vn_turn_integration import TurnRoles, install_roles, seed_vn


async def test_rp_wear_partial_restore_remove_and_next_scene(monkeypatch):
    texts = [
        "Lina puts on her blue shirt.",
        "Lina raises her blue shirt above her waist.",
        "Lina waits by the doorway.",
        "Lina lowers her blue shirt again.",
        "Lina removes her blue shirt.",
    ]
    shirt = deepcopy(fixtures()[1].items["SHIRT"])

    class WardrobeRoles(TurnRoles):
        turn = 0

        async def structured(self, *args, **kwargs):
            schema = kwargs.get("response_model") or args[2]
            if issubclass(schema, ItemExtraction):
                actions = (
                    []
                    if self.turn == 2
                    else [
                        ItemAction(
                            item_id="SHIRT",
                            source_owner="LINA",
                            destination_owner="LINA",
                            disposition="carried" if self.turn == 4 else "worn",
                            basis="completed",
                            uncovered_regions=["torso"]
                            if self.turn == 1
                            else []
                            if self.turn == 3
                            else None,
                            evidence=texts[self.turn],
                        )
                    ]
                )
                return extraction(schema, actions=actions)
            return await super().structured(*args, **kwargs)

    roles = WardrobeRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.id == "LINA", WorldEntity.session_id == state.session_id
            )
        )
        npc.inventory = [shirt]
        npc.age_years = 30
        npc.visual_profile = {
            "appearance": {"age_years": 30},
            "worn": [],
            "body": {"form": "humanoid"},
        }
        await db.commit()
        for turn, text in enumerate(texts):
            roles.turn = turn
            monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", text)
            manager = GameTurnManager(db, "session-1", user)
            chunks = [chunk async for chunk in manager.process_turn("Continue.")]
            assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
            await db.refresh(state)
            view = await character_current_state(db, state, npc)
            clothes = view["clothing"]["items"]
            assert bool(clothes) is (turn < 4)
            if turn < 4:
                assert clothes[0]["item_id"] == "SHIRT" and clothes[0]["slots"] == ["Chest"]
                assert clothes[0]["uncovered_regions"] == (["torso"] if turn in (1, 2) else [])
            if turn == 1:
                worn = state.entity_states["LINA"]["visual_profile"]["worn"][0]
                message = await db.get(ChatMessage, worn["source"]["source_message_id"])
                assert message.role == "assistant" and message.content == text
                original = deepcopy(worn)
            if turn == 2:
                assert state.entity_states["LINA"]["visual_profile"]["worn"][0] == original
                assert "known_worn_placements" in str(roles.prompts[-1])
                # A new scene and a fresh manager keep the same canonical placement.
                state.current_scene_id = "TOWER"
                state.entity_states = {
                    **state.entity_states,
                    "LINA": {**state.entity_states["LINA"], "current_scene_id": "TOWER"},
                }
                await db.commit()
                assert (await character_current_state(db, state, npc))["clothing"]["items"][0][
                    "uncovered_regions"
                ] == ["torso"]
        assert [item["id"] for item in state.entity_states["LINA"]["inventory"]] == ["SHIRT"]
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        assert state.entity_states["LINA"]["visual_profile"]["worn"] == []


def test_source_remapping_keeps_placement_and_reasoning_omits_proof_payload():
    from tests.test_body_equipment import attach, setup_body
    from tests.test_narrated_items import run

    actors, snapshot = setup_body(["anal"])
    changed, accepted, errors = run([attach()], actors, snapshot)
    assert accepted and not errors
    raw = changed["NPC"]["visual_profile"]
    raw["worn"][-1]["source"]["source_message_id"] = "answer"
    mapped = remap_profile(raw, {"TURN": "new-request", "answer": "new-answer"})
    source = mapped["worn"][-1]["source"]
    assert source["request_id"] == "new-request" and source["source_message_id"] == "new-answer"
    assert mapped["worn"][-1]["attachment_slot"] == "anal"
    unavailable = remap_profile(raw, {})["worn"][-1]
    assert (
        unavailable["source"]["source_message_id"] is None
        and unavailable["attachment_slot"] == "anal"
    )
    context = actor_context(changed)
    assert "attachment_slot" in str(context) and "content_hash" not in str(context)
    assert "source_message_id" not in str(context)
