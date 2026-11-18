"""Saved wardrobe evidence survives application without becoming an actor command."""

import json
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine import turn_controls
from backend.engine.clothing.planning import prepare_wardrobe_plan, validate_plan
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.runtime import apply_wardrobe
from backend.engine.clothing.wear_provenance import source_matches
from backend.engine.gameplay.turn_prompt_layout import build_outcome_json
from backend.engine.rule_engine import GameEvent
from backend.engine.visual_novel.continuity import PLAYER
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_clothing_runtime import (
    ACTION,
    ClothingRoles,
    action,
    creation,
    item,
    profile,
    world,
)
from tests.test_vn_turn_integration import install_roles, seed_vn


async def prepared(db, *, source="player_action"):
    user, avatar, _state, previous_id = await seed_vn(db)
    avatar.inventory, avatar.visual_profile = [item()], profile("coat")
    previous = await db.get(ChatMessage, previous_id)
    previous.content = "The traveler raises the coat sleeves."
    request = ChatMessage(session_id="session-1", role="user", content=ACTION, scene_id="START")
    db.add(request)
    await db.commit()
    manager = GameTurnManager(db, "session-1", user)
    await manager.initialize()
    manager._vn_player_message_id = request.id
    turn_controls.begin(manager)
    turn_controls.bind_input(manager, request)
    evidence = ACTION if source == "player_action" else previous.content
    proposal = SimpleNamespace(
        wardrobe_actions=[
            action(source=source, evidence=evidence, operation="adjust", uncovered_regions=["arms"])
        ],
        garment_creations=[],
    )
    event = GameEvent()
    await prepare_wardrobe_plan(manager, event, proposal, ACTION, [], [])
    return manager, event, request, previous


@pytest.mark.asyncio
async def test_real_turn_saves_user_wear_source_and_structured_owner_outcome(monkeypatch):
    roles = ClothingRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, _state, _previous = await seed_vn(db)
        avatar.inventory, avatar.visual_profile = [item()], profile()
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn(ACTION)]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        request = await db.scalar(
            select(ChatMessage).where(ChatMessage.id == manager._vn_player_message_id)
        )
        await db.refresh(avatar)
        worn = load_profile(avatar.visual_profile).worn[0]
        assert worn.source is not None
        source = worn.source.model_dump()
        assert source["source_message_id"] == request.id == source["request_id"]
        assert source["source_role"] == "user"
        assert source["content_hash"] == sha256(ACTION.encode()).hexdigest()
        assert source_matches(source, request.content)
        assert "command" not in source
        assert "preliminary_player_wardrobe_outcomes" in str(roles.prompts[-1])
        assert len(roles.calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("source_kind", ["player_action", "completed_narration"])
async def test_applied_receipt_uses_saved_source_and_actual_coverage(source_kind):
    async with TestSessionLocal() as db:
        manager, event, request, previous = await prepared(db, source=source_kind)
        await apply_wardrobe(manager, event, manager.state.entity_states)
        _draft, raw = build_outcome_json(event)
        receipt = json.loads(raw)["preliminary_player_wardrobe_outcomes"][0]
        source = request if source_kind == "player_action" else previous
        assert receipt["actor_id"] == PLAYER and receipt["item_id"] == "coat"
        assert receipt["status"] == "applied" and receipt["reason_code"] == "applied"
        assert receipt["uncovered_regions"] == ["arms"]
        assert receipt["source_message_id"] == source.id
        assert receipt["source_revision_id"] == source.revision_id
        assert receipt["source_role"] == source.role
        assert receipt["control"]["input_id"] == request.id
        assert "command_id" not in receipt["control"]
        saved_source = manager.avatar.visual_profile["worn"][0]["source"]
        assert source_matches(saved_source, source.content)
        assert saved_source["source_message_id"] == source.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["edit", "revision", "different_input", "foreign_session", "scene", "attempt", "delete"],
)
async def test_stale_saved_source_never_replaces_worn_state(change):
    async with TestSessionLocal() as db:
        manager, event, request, _previous = await prepared(db)
        before = load_profile(deepcopy(manager.avatar.visual_profile)).model_dump()
        if change == "edit":
            request.content = ACTION + " That was only a proposed action."
        if change == "revision":
            request.revision_id = "changed-revision"
        if change == "different_input":
            event._vn_clothing_plan.message_id = "different-input"
        if change == "foreign_session":
            original = await db.get(GameSession, "session-1")
            db.add(
                GameSession(
                    id="other-session", user_id=original.user_id, avatar_id=original.avatar_id
                )
            )
            await db.flush()
            request.session_id = "other-session"
        if change == "scene":
            manager.state.current_scene_id = "ELSEWHERE"
        if change == "attempt":
            turn_controls.begin(manager)
            turn_controls.bind_input(manager, request)
        if change == "delete":
            await db.delete(request)
        await db.flush()
        await apply_wardrobe(manager, event, manager.state.entity_states)
        assert manager.avatar.visual_profile == before
        _draft, raw = build_outcome_json(event)
        receipt = json.loads(raw)["preliminary_player_wardrobe_outcomes"][0]
        assert receipt["status"] == "blocked"
        assert receipt["reason_code"] in {"source_changed", "actor_unavailable"}


@pytest.mark.asyncio
async def test_direct_legacy_plan_never_invents_saved_source_or_command():
    manager, npc, scenes = world()
    event = GameEvent()
    event._vn_clothing_plan = validate_plan(
        manager, SimpleNamespace(wardrobe_actions=[action()]), ACTION, "", [npc], scenes
    )
    await apply_wardrobe(manager, event, manager.state.entity_states)
    assert load_profile(manager.avatar.visual_profile).worn[0].source is None


@pytest.mark.asyncio
async def test_ownership_rejection_receipt_cannot_report_a_completed_adjustment():
    async with TestSessionLocal() as db:
        manager, event, _request, _previous = await prepared(db)
        manager.avatar.inventory = []
        await apply_wardrobe(manager, event, manager.state.entity_states)
        _draft, raw = build_outcome_json(event)
        receipt = json.loads(raw)["preliminary_player_wardrobe_outcomes"][0]
        assert receipt["status"] == "blocked"
        assert receipt["reason_code"] == "wardrobe_rejected"
        assert "uncovered_regions" not in receipt
        assert load_profile(manager.avatar.visual_profile).worn == []


@pytest.mark.asyncio
async def test_creation_wear_carries_the_same_saved_player_evidence():
    async with TestSessionLocal() as db:
        manager, _event, request, _previous = await prepared(db)
        request.content = "I buy a red scarf and put it on."
        await db.flush()
        turn_controls.bind_input(manager, request)
        proposal = SimpleNamespace(
            wardrobe_actions=[],
            garment_creations=[creation(evidence=request.content, source_id="START", wear=True)],
        )
        event = GameEvent()
        await prepare_wardrobe_plan(
            manager,
            event,
            proposal,
            request.content,
            [],
            [{"id": "START", "description": "An established clothing shop."}],
        )
        await apply_wardrobe(manager, event, manager.state.entity_states)
        worn = load_profile(manager.avatar.visual_profile).worn
        scarf = next(row for row in worn if row.item_id != "coat")
        assert scarf.source.source_role == "user"
        assert scarf.source.source_message_id == request.id
        assert source_matches(scarf.source.model_dump(), request.content)
        _draft, raw = build_outcome_json(event)
        receipt = json.loads(raw)["preliminary_player_wardrobe_outcomes"][0]
        assert receipt["operation"] == "create" and receipt["item_id"] == scarf.item_id
        assert receipt["worn"] is True and receipt["uncovered_regions"] == []


@pytest.mark.asyncio
async def test_rollback_and_retry_do_not_reuse_the_previous_attempt_receipt():
    async with TestSessionLocal() as db:
        manager, old_event, request, _previous = await prepared(db)
        await apply_wardrobe(manager, old_event, manager.state.entity_states)
        _draft, raw = build_outcome_json(old_event)
        first = json.loads(raw)["preliminary_player_wardrobe_outcomes"][0]
        await db.flush()
        await db.rollback()
        await db.refresh(manager.avatar)
        await db.refresh(manager.state)
        await db.refresh(request)
        assert load_profile(manager.avatar.visual_profile).worn[0].source is None
        turn_controls.begin(manager)
        turn_controls.bind_input(manager, request)
        event = GameEvent()
        await prepare_wardrobe_plan(
            manager, event, SimpleNamespace(wardrobe_actions=[action()]), ACTION, [], []
        )
        await apply_wardrobe(manager, event, manager.state.entity_states)
        _draft, raw = build_outcome_json(event)
        retry = json.loads(raw)["preliminary_player_wardrobe_outcomes"][0]
        assert retry["status"] == "applied"
        assert retry["control"]["attempt_id"] != first["control"]["attempt_id"]
        assert retry["control"]["operation_id"] != first["control"]["operation_id"]
        assert retry["source_message_id"] == first["source_message_id"] == request.id


@pytest.mark.asyncio
async def test_no_wardrobe_plan_emits_no_wardrobe_receipts():
    manager, _npc, _scenes = world()
    event = GameEvent()
    await apply_wardrobe(manager, event, manager.state.entity_states)
    _draft, raw = build_outcome_json(event)
    assert "preliminary_player_wardrobe_outcomes" not in json.loads(raw)


@pytest.mark.asyncio
async def test_edited_narration_cannot_supply_stale_wardrobe_evidence():
    async with TestSessionLocal() as db:
        manager, event, _request, previous = await prepared(db, source="completed_narration")
        previous.content += " The earlier description was revised."
        await db.flush()
        await apply_wardrobe(manager, event, manager.state.entity_states)
        _draft, raw = build_outcome_json(event)
        receipt = json.loads(raw)["preliminary_player_wardrobe_outcomes"][0]
        assert receipt["status"] == "blocked" and receipt["reason_code"] == "source_changed"
        assert load_profile(manager.avatar.visual_profile).worn[0].source is None


@pytest.mark.asyncio
async def test_gift_from_existing_actor_description_needs_no_prior_narration():
    async with TestSessionLocal() as db:
        manager, _event, request, previous = await prepared(db)
        await db.delete(previous)
        entities = list(
            (
                await db.scalars(select(WorldEntity).where(WorldEntity.session_id == "session-1"))
            ).all()
        )
        giver = next(row for row in entities if row.id == "LINA")
        giver.description = "A shopkeeper offers a new red scarf."
        request.content = "I accept the red scarf and put it on."
        await db.flush()
        turn_controls.bind_input(manager, request)
        proposal = SimpleNamespace(
            wardrobe_actions=[],
            garment_creations=[
                creation(
                    evidence=request.content,
                    acquisition="gift",
                    source_id="LINA",
                    source_evidence="A shopkeeper offers a new red scarf.",
                    wear=True,
                )
            ],
        )
        event = GameEvent()
        await prepare_wardrobe_plan(manager, event, proposal, request.content, entities, [])
        await apply_wardrobe(manager, event, manager.state.entity_states)
        _draft, raw = build_outcome_json(event)
        receipt = json.loads(raw)["preliminary_player_wardrobe_outcomes"][0]
        assert receipt["operation"] == "create" and receipt["status"] == "applied"
        assert receipt["source_message_id"] == request.id


@pytest.mark.asyncio
async def test_narration_changed_during_source_capture_cannot_mint_valid_provenance(monkeypatch):
    async with TestSessionLocal() as db:
        manager, _event, request, previous = await prepared(db, source="completed_narration")
        original = db.get
        evidence = previous.content
        changed = False

        async def read(model, identifier, **kwargs):
            nonlocal changed
            if identifier == request.id and not changed:
                previous.content = "The traveler leaves the coat untouched."
                changed = True
            return await original(model, identifier, **kwargs)

        monkeypatch.setattr(db, "get", read)
        event = GameEvent()
        await prepare_wardrobe_plan(
            manager,
            event,
            SimpleNamespace(
                wardrobe_actions=[
                    action(source="completed_narration", evidence=evidence, operation="adjust")
                ]
            ),
            ACTION,
            [],
            [],
        )
        await db.flush()
        await apply_wardrobe(manager, event, manager.state.entity_states)
        _draft, raw = build_outcome_json(event)
        receipt = json.loads(raw)["preliminary_player_wardrobe_outcomes"][0]
        assert receipt["status"] == "blocked"
        assert load_profile(manager.avatar.visual_profile).worn[0].source is None
