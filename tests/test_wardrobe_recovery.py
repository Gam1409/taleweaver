"""Wardrobe recovery previews, source validation and stale-state protection."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.clothing.recovery import RecoveryEntry, RecoveryProposal, evaluate
from backend.engine.clothing.recovery_context import KEY
from backend.engine.debug_engine import DebugEngine
from backend.engine.narrated_items.schema import ItemAction
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_narrated_items import fixtures
from tests.test_vn_turn_integration import seed_vn

TEXT = "Лина стоит в синем хлопковом халате."


def entry(source, npc="LINA", name="Синий халат"):
    return RecoveryEntry(
        source_message_id=source,
        action=ItemAction(
            source_owner=npc,
            destination_owner=npc,
            disposition="worn",
            basis="observed_wear",
            evidence=TEXT,
            new_item={
                "name": name,
                "description": "Синий хлопковый халат.",
                "kind": "clothing",
                "clothing": {"layer": 2, "coverage": ["torso", "arms"]},
                "wearable_slots": ["Chest"],
            },
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", [None, "story", "state", "revision"])
async def test_preview_does_not_mutate_and_apply_requires_unchanged_history(monkeypatch, stale):
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        message = ChatMessage(
            session_id=state.session_id, role="assistant", content=TEXT, scene_id="START"
        )
        db.add(message)
        await db.commit()
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        old_inventory = deepcopy(npc.inventory)
        llm = SimpleNamespace(
            model="test",
            aexecute_complex_task=AsyncMock(
                return_value=RecoveryProposal(entries=[entry(message.id)])
            ),
        )
        monkeypatch.setattr(
            "backend.engine.clothing.recovery.GameMasterLLM.for_role", lambda *_: llm
        )
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_preview LINA", user=user, avatar=avatar
        )
        assert "preview ready" in result, result
        preview = state.entity_states[KEY]
        assert "LINA" not in state.entity_states
        assert npc.inventory == old_inventory
        assert preview["accepted"][0]["source_message_id"] == message.id
        if stale == "story":
            db.add(
                ChatMessage(
                    session_id=state.session_id,
                    role="assistant",
                    content="Лина сняла халат и отдала его герою.",
                )
            )
        elif stale == "state":
            state.entity_states = {**state.entity_states, "LINA": {"current_scene_id": "FOREST"}}
        elif stale == "revision":
            message.content = "Лина больше не носит халат."
        await db.flush()
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_apply " + preview["token"], user=user, avatar=avatar
        )
        if stale:
            assert "changed after preview" in result
            assert not (state.entity_states.get("LINA") or {}).get("inventory")
            return
        assert "Recovered 1" in result, result
        await db.commit()
        await db.refresh(state)
        saved = state.entity_states["LINA"]
        assert saved["inventory"][0] == old_inventory[0]
        item = saved["inventory"][1]
        assert item["item_origin"]["source_message_id"] == message.id
        assert saved["visual_profile"]["worn"][0]["item_id"] == item["id"]
        assert KEY not in state.entity_states
        again = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_apply " + preview["token"], user=user, avatar=avatar
        )
        assert "missing or has been replaced" in again


def test_invalid_history_source_and_other_owner_are_rejected():
    actors, snapshot = fixtures()
    for proposal in [entry("user", "NPC"), entry("missing", "NPC"), entry("assistant", "OTHER")]:
        context = {
            "actor": actors["NPC"],
            "snapshot": snapshot,
            "messages": [
                {"id": "user", "role": "user", "content": TEXT},
                {"id": "assistant", "role": "assistant", "content": TEXT},
            ],
        }
        _, accepted, errors = evaluate(
            context, RecoveryProposal(entries=[proposal]), True, "session"
        )
        assert errors and not accepted


def test_two_garments_from_one_message_have_distinct_ids_and_real_provenance():
    actors, snapshot = fixtures()
    context = {
        "actor": actors["NPC"],
        "snapshot": snapshot,
        "messages": [{"id": "source", "role": "assistant", "content": TEXT}],
    }
    changed, accepted, errors = evaluate(
        context,
        RecoveryProposal(entries=[entry("source", "NPC"), entry("source", "NPC", "Scarf")]),
        True,
        "session",
    )
    assert not errors and len(accepted) == 2
    ids = {item["item"]["id"] for item in accepted}
    assert len(ids) == 2
    assert all(
        item["item_origin"]["source_message_id"] == "source"
        for item in changed["NPC"]["inventory"]
        if item["id"] in ids
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError(), ValueError("")])
async def test_preview_failure_is_visible_durable_and_uses_role_deadline(monkeypatch, failure):
    from backend.engine.clothing import recovery

    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        state_before = deepcopy(state.entity_states)
        llm = SimpleNamespace(model="test", aexecute_complex_task=AsyncMock(side_effect=failure))
        monkeypatch.setattr(recovery.GameMasterLLM, "for_role", lambda *_: llm)
        monkeypatch.setattr(recovery, "role_timeout", lambda *_: 600.0)

        async def wait_for(request, *, timeout):
            assert timeout == 600.0
            return await request

        monkeypatch.setattr(recovery.asyncio, "wait_for", wait_for)
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_preview LINA", user=user, avatar=avatar
        )
        assert "No clothing was changed" in result
        if isinstance(failure, TimeoutError):
            assert "timed out" in result and "600s" in result
        else:
            assert "ValueError" in result
        preview = state.entity_states[KEY]
        assert preview["errors"] and preview["accepted"] == []
        assert {k: v for k, v in state.entity_states.items() if k != KEY} == state_before
        assert "rejected or empty" in await DebugEngine.handle_debug_command(
            db, state, "wardrobe_apply " + preview["token"], user=user, avatar=avatar
        )


@pytest.mark.asyncio
async def test_uncertain_queue_is_not_reported_as_invalid_recovery_result(monkeypatch):
    from backend.core.inference.registry import InferenceUncertainError
    from backend.engine.clothing import recovery

    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        llm = SimpleNamespace(
            model="test",
            aexecute_complex_task=AsyncMock(side_effect=InferenceUncertainError("blocked")),
        )
        monkeypatch.setattr(recovery.GameMasterLLM, "for_role", lambda *_: llm)
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_preview LINA", user=user, avatar=avatar
        )
        assert "No recovery request was sent" in result
        assert "verifying generation has stopped" in result
        assert "Invalid recovery result" not in result
        assert not state.entity_states[KEY]["accepted"]


def test_recovery_keeps_all_confirmed_layers_and_partial_placement():
    actors, snapshot = fixtures()
    text = "Anna wears a coat, jacket, skirt, stockings, scarf, gloves and hat. The skirt is lifted above her legs."
    entries = []
    for name in ("Coat", "Jacket", "Skirt", "Stockings", "Scarf", "Gloves", "Hat"):
        candidate = entry("source", "NPC", name)
        candidate.action.evidence = text
        candidate.action.new_item.clothing.coverage = ["legs"] if name == "Skirt" else ["torso"]
        if name == "Skirt":
            candidate.uncovered_regions = ["legs"]
            candidate.placement_evidence = "The skirt is lifted above her legs."
        entries.append(candidate)
    context = {
        "actor": actors["NPC"],
        "snapshot": snapshot,
        "messages": [{"id": "source", "role": "assistant", "content": text}],
    }
    changed, accepted, errors = evaluate(context, RecoveryProposal(entries=entries), True, "s")
    assert len(accepted) == 7 and not errors
    skirt = next(row for row in accepted if row["item"]["name"] == "Skirt")
    assert skirt["uncovered_regions"] == ["legs"]
    assert next(
        row
        for row in changed["NPC"]["visual_profile"]["worn"]
        if row["item_id"] == skirt["item"]["id"]
    )["uncovered_regions"] == ["legs"]


@pytest.mark.parametrize("regions,evidence", [(["feet"], TEXT), (["torso"], "invented quote")])
def test_partial_placement_rejects_wrong_coverage_or_missing_evidence(regions, evidence):
    actors, snapshot = fixtures()
    candidate = entry("source", "NPC")
    candidate.uncovered_regions, candidate.placement_evidence = regions, evidence
    context = {
        "actor": actors["NPC"],
        "snapshot": snapshot,
        "messages": [{"id": "source", "role": "assistant", "content": TEXT}],
    }
    changed, accepted, errors = evaluate(context, RecoveryProposal(entries=[candidate]), True, "s")
    assert not accepted and errors and changed["NPC"] == actors["NPC"]


@pytest.mark.asyncio
@pytest.mark.parametrize("detailed", [True, False])
async def test_preview_sends_clothing_detail_setting_to_model(monkeypatch, detailed):
    import json

    from backend.engine.clothing import recovery

    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        state.entity_states = {
            **state.entity_states,
            "__manifest_snapshot__": {
                "original_manifest": {"clothing_settings": {"detailed": detailed}}
            },
        }
        llm = SimpleNamespace(
            model="test", aexecute_complex_task=AsyncMock(return_value=RecoveryProposal())
        )
        monkeypatch.setattr(recovery.GameMasterLLM, "for_role", lambda *_: llm)
        result = await DebugEngine.handle_debug_command(
            db, state, "wardrobe_preview LINA", user=user, avatar=avatar
        )
        assert "preview ready" in result
        assert (
            json.loads(llm.aexecute_complex_task.call_args.args[1])["detailed_clothing"] is detailed
        )
