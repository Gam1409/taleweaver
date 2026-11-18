"""Creation recovery checks the historical giver as well as the recipient."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine import turn_controls
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.engine.clothing.planning import prepare_wardrobe_plan
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.runtime import apply_wardrobe
from backend.engine.gameplay.turn_prompt_layout import build_outcome_json
from backend.engine.rule_engine import GameEvent
from backend.engine.visual_novel import movement_sources
from backend.engine.visual_novel.continuity import PLAYER
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_clothing_runtime import action, creation
from tests.test_wardrobe_historical_sources import apply, context

GIFT = "Lina gives the traveler a red scarf."


async def gift_context(db, primary, *, authored=False, controlled=True):
    manager, giver, request, previous = await context(db)
    previous.content = GIFT
    previous.npc_recovery = {
        **previous.npc_recovery,
        "content_hash": digest(GIFT),
        "command_controlled_actor_ids": ["LINA"] if controlled else ["OTHER"],
    }
    giver.description = (
        "A shopkeeper carries a new red scarf." if authored else "A shopkeeper in a blue coat."
    )
    request.content = "I receive the offered red scarf and put it on."
    await db.flush()
    turn_controls.bind_input(manager, request)
    await movement_sources.prepare(manager)
    proposed = creation(
        actor_id=PLAYER,
        source=primary,
        evidence=request.content if primary == "player_action" else GIFT,
        acquisition="gift",
        source_id="LINA",
        source_evidence=giver.description if authored else "a red scarf",
        wear=True,
    )
    event = GameEvent()
    await prepare_wardrobe_plan(
        manager,
        event,
        SimpleNamespace(garment_creations=[proposed]),
        request.content,
        [giver],
        [],
    )
    return manager, event


@pytest.mark.parametrize("primary", ["completed_narration", "player_action"])
async def test_controlled_historical_giver_cannot_create_an_unexecuted_gift(primary):
    async with TestSessionLocal() as db:
        manager, event = await gift_context(db, primary)
        before = deepcopy(manager.avatar.inventory)
        receipt = await apply(manager, event)
        assert manager.avatar.inventory == before
        assert receipt["status"] == "blocked"
        assert receipt["reason_code"] == "historical_command_owned"


@pytest.mark.parametrize("primary", ["completed_narration", "player_action"])
async def test_unmarked_giver_keeps_existing_narrative_gift_recovery(primary):
    async with TestSessionLocal() as db:
        manager, event = await gift_context(db, primary, controlled=False)
        receipt = await apply(manager, event)
        assert receipt["status"] == "applied"
        assert any(row["name"] == "Red scarf" for row in manager.avatar.inventory)


async def test_current_player_acquisition_keeps_its_authored_giver_source():
    async with TestSessionLocal() as db:
        manager, event = await gift_context(db, "player_action", authored=True)
        assert not event._vn_clothing_plan.requires_narration
        receipt = await apply(manager, event)
        assert receipt["status"] == "applied"
        assert any(row["name"] == "Red scarf" for row in manager.avatar.inventory)


async def test_rejected_earlier_peer_cannot_shift_a_gift_onto_authored_source_authority():
    async with TestSessionLocal() as db:
        manager, original = await gift_context(db, "player_action")
        saved_input = await db.get(ChatMessage, manager._vn_player_message_id)
        saved_input.content = "I buy a blue ribbon and receive the offered red scarf."
        await db.flush()
        turn_controls.bind_input(manager, saved_input)
        await movement_sources.prepare(manager)
        gift = original._vn_clothing_plan.creations[0].model_copy(
            update={"evidence": saved_input.content}
        )
        authored = creation(
            evidence=saved_input.content,
            acquisition="shop",
            source_id="START",
            source_evidence="An established clothing shop",
            name="Blue ribbon",
        )
        invalid = authored.model_copy(update={"source_id": "UNAVAILABLE", "name": "Grey shawl"})
        event = GameEvent()
        entities = list((await db.scalars(select(WorldEntity))).all())
        await prepare_wardrobe_plan(
            manager,
            event,
            SimpleNamespace(garment_creations=[invalid, authored, gift]),
            saved_input.content,
            entities,
            [{"id": "START", "description": "An established clothing shop."}],
        )
        assert event._vn_clothing_plan.narrated_gift_indices == {1}
        await apply(manager, event)
        names = {row["name"] for row in manager.avatar.inventory}
        assert "Blue ribbon" in names
        assert not names & {"Red scarf", "Grey shawl"}


@pytest.mark.parametrize("changed", ["marker", "content"])
async def test_invalid_old_gift_source_keeps_an_independent_current_player_adjustment(changed):
    async with TestSessionLocal() as db:
        manager, original = await gift_context(db, "player_action")
        request = await db.get(ChatMessage, manager._vn_player_message_id)
        request.content = "I raise my coat sleeves and take the offered red scarf."
        await db.flush()
        turn_controls.bind_input(manager, request)
        await movement_sources.prepare(manager)
        gift = original._vn_clothing_plan.creations[0].model_copy(
            update={"evidence": request.content}
        )
        rows = list((await db.scalars(select(WorldEntity))).all())
        event = GameEvent()
        await prepare_wardrobe_plan(
            manager,
            event,
            SimpleNamespace(
                wardrobe_actions=[
                    action(evidence=request.content, operation="adjust", uncovered_regions=["arms"])
                ],
                garment_creations=[gift],
            ),
            request.content,
            rows,
            [],
        )
        previous = await db.get(ChatMessage, event._vn_clothing_plan.sources.narration.message_id)
        if changed == "marker":
            previous.npc_recovery = None
        else:
            previous.content += " This account was revised."
        await db.flush()
        await apply_wardrobe(manager, event, manager.state.entity_states)
        worn = load_profile(manager.avatar.visual_profile).worn[0]
        assert worn.uncovered_regions == ["arms"]
        assert worn.source.source_role == "user" and worn.source.source_message_id == request.id
        _draft, raw = build_outcome_json(event)
        receipts = json.loads(raw)["preliminary_player_wardrobe_outcomes"]
        assert any(
            row["operation"] == "create" and row["reason_code"] == "source_changed"
            for row in receipts
        )
        assert any(row.get("item_id") == "coat" and row["status"] == "applied" for row in receipts)
        assert not any(row["name"] == "Red scarf" for row in manager.avatar.inventory)


async def test_current_controlled_giver_requires_a_linked_player_acquisition():
    async with TestSessionLocal() as db:
        manager, original = await gift_context(db, "player_action", authored=True)
        kernel = KernelState(
            settings=Settings(
                mode="live",
                workflow="integrated",
                action_tools=True,
                actor_ids=["LINA"],
                agent_steps=1,
            )
        )
        manager.state.entity_states = {**manager.state.entity_states, KEY: kernel.model_dump()}
        request = await db.get(ChatMessage, manager._vn_player_message_id)
        rows = list((await db.scalars(select(WorldEntity))).all())
        event = GameEvent()
        await prepare_wardrobe_plan(
            manager,
            event,
            SimpleNamespace(garment_creations=original._vn_clothing_plan.creations),
            request.content,
            rows,
            [],
        )
        before = deepcopy(manager.avatar.inventory)
        await apply_wardrobe(manager, event, manager.state.entity_states)
        assert manager.avatar.inventory == before


async def test_input_edited_while_old_narration_is_read_invalidates_all_current_changes(
    monkeypatch,
):
    async with TestSessionLocal() as db:
        manager, original = await gift_context(db, "player_action")
        request = await db.get(ChatMessage, manager._vn_player_message_id)
        rows = list((await db.scalars(select(WorldEntity))).all())
        event = GameEvent()
        await prepare_wardrobe_plan(
            manager,
            event,
            SimpleNamespace(
                wardrobe_actions=[
                    action(evidence=request.content, operation="adjust", uncovered_regions=["arms"])
                ],
                garment_creations=original._vn_clothing_plan.creations,
            ),
            request.content,
            rows,
            [],
        )
        previous_id = event._vn_clothing_plan.sources.narration.message_id
        original_get = db.get

        async def edited_during_read(model, identifier, **kwargs):
            result = await original_get(model, identifier, **kwargs)
            if identifier == previous_id:
                request.content += " The current action was revised."
            return result

        monkeypatch.setattr(db, "get", edited_during_read)
        await apply_wardrobe(manager, event, manager.state.entity_states)
        assert load_profile(manager.avatar.visual_profile).worn[0].uncovered_regions == []
        _draft, raw = build_outcome_json(event)
        receipts = json.loads(raw)["preliminary_player_wardrobe_outcomes"]
        assert all(row["status"] == "blocked" for row in receipts)
