"""Historical wardrobe authority remains source-bound across pauses and portability."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine import turn_controls
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.recovery_contracts import RecoveryAudit
from backend.engine.clothing import runtime
from backend.engine.clothing.planning import prepare_wardrobe_plan
from backend.engine.clothing.profiles import load_profile
from backend.engine.gameplay.turn_prompt_layout import build_outcome_json
from backend.engine.npc_actions import source_control
from backend.engine.npc_journal.messages import copy_messages, restore_messages
from backend.engine.rule_engine import GameEvent
from backend.engine.visual_novel import movement_sources
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_clothing_plan_sources import prepared
from tests.test_clothing_runtime import action, item, profile

TEXT = "Lina raises the sleeves of her coat."


async def context(db, marker=True):
    manager, _event, request, previous = await prepared(db)
    npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
    npc.inventory = [item("NPC_COAT")]
    npc.visual_profile = load_profile(profile("NPC_COAT")).model_dump()
    manager.avatar.visual_profile = load_profile(manager.avatar.visual_profile).model_dump()
    previous.content = TEXT
    audit = RecoveryAudit(
        content_hash=digest(TEXT), revision_id=previous.revision_id, scene_id="START", actors={}
    )
    if marker:
        audit.command_controlled_actor_ids = ["LINA"]
    previous.npc_recovery = audit.model_dump()
    await db.flush()
    await movement_sources.prepare(manager)
    return manager, npc, request, previous


async def proposal(manager, npc, request, *, source="completed_narration", **changes):
    change = action(
        **{
            "actor_id": "LINA",
            "item_id": "NPC_COAT",
            "source": source,
            "evidence": TEXT if source == "completed_narration" else request.content,
            "operation": "adjust",
            "uncovered_regions": ["arms"],
            "agency": "npc_choice" if source == "completed_narration" else "consented_assistance",
            "npc_decision": "approved",
            **changes,
        }
    )
    event = GameEvent()
    await prepare_wardrobe_plan(
        manager, event, SimpleNamespace(wardrobe_actions=[change]), request.content, [npc], []
    )
    return event


async def apply(manager, event):
    await runtime.apply_wardrobe(manager, event, manager.state.entity_states)
    _draft, payload = build_outcome_json(event)
    return json.loads(payload)["preliminary_player_wardrobe_outcomes"][0]


def current_profile(manager, npc):
    raw = manager.state.entity_states.get(npc.id, {}).get("visual_profile", npc.visual_profile)
    return load_profile(raw)


@pytest.mark.parametrize("phase", ["before_prepare", "during_capture", "before_apply"])
async def test_marker_downgrade_cannot_turn_a_captured_controlled_source_into_legacy(
    monkeypatch, phase
):
    async with TestSessionLocal() as db:
        manager, npc, request, previous = await context(db)
        original = db.get

        async def changed(model, identifier, **kwargs):
            if phase == "during_capture" and identifier == request.id:
                previous.npc_recovery = {
                    key: value
                    for key, value in previous.npc_recovery.items()
                    if key != "command_controlled_actor_ids"
                }
            return await original(model, identifier, **kwargs)

        if phase == "before_prepare":
            previous.npc_recovery = None
            await db.flush()
        monkeypatch.setattr(db, "get", changed)
        event = await proposal(manager, npc, request)
        if phase == "before_apply":
            previous.npc_recovery = None
            await db.flush()
        receipt = await apply(manager, event)
        assert receipt["status"] == "blocked" and receipt["reason_code"] == "source_changed"
        assert current_profile(manager, npc).worn[0].uncovered_regions == []


@pytest.mark.parametrize("change", ["content_hash", "revision_id", "scene_id", "malformed"])
async def test_stale_or_malformed_present_authority_is_not_legacy(change):
    async with TestSessionLocal() as db:
        manager, npc, request, previous = await context(db)
        audit = deepcopy(previous.npc_recovery)
        if change == "malformed":
            audit["command_controlled_actor_ids"] = "LINA"
        else:
            audit[change] = "a" * 64 if change == "content_hash" else "changed"
        previous.npc_recovery = audit
        await db.flush()
        await movement_sources.prepare(manager)
        event = await proposal(manager, npc, request)
        receipt = await apply(manager, event)
        assert receipt["status"] == "blocked" and receipt["reason_code"] == "source_changed"
        assert current_profile(manager, npc).worn[0].uncovered_regions == []


@pytest.mark.parametrize("legacy", ["no_envelope", "old_envelope", "null_marker"])
async def test_valid_legacy_sources_keep_completed_narration_recovery(legacy):
    async with TestSessionLocal() as db:
        manager, npc, request, previous = await context(db, marker=False)
        if legacy == "no_envelope":
            previous.npc_recovery = None
        if legacy == "null_marker":
            previous.npc_recovery = {**previous.npc_recovery, "command_controlled_actor_ids": None}
        await db.flush()
        await movement_sources.prepare(manager)
        event = await proposal(manager, npc, request)
        receipt = await apply(manager, event)
        assert receipt["status"] == "applied" and receipt["reason_code"] == "applied"
        assert current_profile(manager, npc).worn[0].uncovered_regions == ["arms"]


async def test_cursor_progress_does_not_invalidate_a_nonmutating_canonical_echo(monkeypatch):
    async with TestSessionLocal() as db:
        manager, npc, request, previous = await context(db)
        event = await proposal(manager, npc, request, uncovered_regions=[])
        previous.npc_recovery = {**previous.npc_recovery, "actors": {"OTHER": 2}}
        await db.flush()

        def unexpected(*_args, **_kwargs):
            raise AssertionError("A historical echo cannot execute wardrobe mutation.")

        monkeypatch.setattr(runtime, "change_owned_wear", unexpected)
        receipt = await apply(manager, event)
        assert receipt["status"] == "applied" and receipt["reason_code"] == "already_current"
        assert current_profile(manager, npc).worn[0].source is None
        assert manager._vn_wardrobe_changed is False


@pytest.mark.parametrize("placement", ["carried", "unknown", "worn"])
async def test_remove_echo_requires_positive_current_carried_state(placement):
    async with TestSessionLocal() as db:
        manager, npc, request, _previous = await context(db)
        if placement != "worn":
            npc.visual_profile = profile()
        if placement == "unknown":
            npc.visual_profile = {**npc.visual_profile, "unassessed_wear_item_ids": ["NPC_COAT"]}
        await db.flush()
        event = await proposal(manager, npc, request, operation="remove", uncovered_regions=[])
        receipt = await apply(manager, event)
        assert receipt["reason_code"] == (
            "already_current" if placement == "carried" else "historical_command_owned"
        )
        assert [row["id"] for row in npc.inventory] == ["NPC_COAT"]


async def test_current_player_assistance_keeps_its_existing_owner_path():
    async with TestSessionLocal() as db:
        manager, npc, request, _previous = await context(db)
        request.content = "I raise Lina's coat sleeves with her agreement."
        await db.flush()
        turn_controls.bind_input(manager, request)
        await movement_sources.prepare(manager)
        event = await proposal(manager, npc, request, source="player_action")
        receipt = await apply(manager, event)
        assert receipt["status"] == "applied" and receipt["reason_code"] == "applied"
        assert current_profile(manager, npc).worn[0].source.source_role == "user"


@pytest.mark.parametrize("mode", ["copy", "import"])
async def test_existing_message_portability_preserves_source_time_control(mode):
    async with TestSessionLocal() as db:
        _manager, _npc, _request, previous = await context(db)
        original = await db.get(GameSession, "session-1")
        db.add(GameSession(id="copied", user_id=original.user_id, avatar_id=original.avatar_id))
        await db.flush()
        if mode == "copy":
            identifiers = await copy_messages(db, "session-1", "copied")
        else:
            identifiers = restore_messages(
                db,
                "copied",
                [
                    {
                        "id": previous.id,
                        "role": previous.role,
                        "content": previous.content,
                        "scene_id": previous.scene_id,
                        "revision_id": previous.revision_id,
                        "npc_recovery": previous.npc_recovery,
                    }
                ],
            )
        await db.flush()
        restored = await db.get(ChatMessage, identifiers[previous.id])
        assert restored.id != previous.id and restored.session_id == "copied"
        assert source_control.read(restored) == source_control.read(previous)
