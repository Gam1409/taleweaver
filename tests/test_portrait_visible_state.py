"""Portraits consume confirmed current surfaces without exposing hidden ledger facts."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.engine.clothing.visuals import npc_visuals
from backend.engine.physical_conditions.ledger import apply, read, remap
from backend.engine.physical_conditions.visuals import retract
from backend.engine.scene_illustrations.snapshots import registry_of
from backend.engine.visual_novel.runtime import capture_completed_moment
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import finish_job, portrait_world, start_job

__all__ = ["portrait_world"]

TORN = "The coat's left sleeve is torn at the elbow."
REPAIRED = "The coat's left sleeve now has a neat square patch."
PROFILE = {
    "version": 1,
    "appearance": {"age_years": 30, "hair": "short dark hair"},
    "worn": [{"item_id": "INNER"}, {"item_id": "COAT"}],
}


def fact(**changes):
    return {
        "operation": "record",
        "target_id": "COAT",
        "kind": "item_state",
        "part": "damage",
        "detail": TORN,
        "evidence": TORN,
        "visibility": "public",
        "visual_detail": TORN,
        "visual_region": "arms",
        **changes,
    }


async def subjects(db):
    state = await db.scalar(
        select(SessionState).where(SessionState.session_id == "portrait-session")
    )
    npc = await db.scalar(
        select(WorldEntity).where(
            WorldEntity.session_id == "portrait-session", WorldEntity.id == "NPC_NEW"
        )
    )
    return state, npc


@pytest_asyncio.fixture
async def wardrobe(portrait_world):
    async with TestSessionLocal() as db:
        _, npc = await subjects(db)
        npc.visual_profile = deepcopy(PROFILE)
        npc.inventory = ["INNER", "COAT"]
        for identifier, name, layer in [
            ("INNER", "Hidden lining", 1),
            ("COAT", "Red coat", 2),
            ("CAPE", "Outer cape", 3),
        ]:
            db.add(
                WorldEntity(
                    id=identifier,
                    session_id="portrait-session",
                    entity_type="OBJECT",
                    name=name,
                    description="Original item description, not a current condition.",
                    current_scene_id="TOWER",
                    metadata_json={"clothing": {"layer": layer, "coverage": ["torso", "arms"]}},
                )
            )
        await db.commit()
    return portrait_world


async def save_facts(proposals, *, detailed=False):
    narration = " ".join(row["evidence"] for row in proposals)
    async with TestSessionLocal() as db:
        state, _ = await subjects(db)
        states, accepted, rejected = apply(
            state.entity_states,
            proposals,
            targets={"NPC_NEW", "OTHER_NPC", "COAT", "INNER"},
            item_targets={"COAT", "INNER"},
            narration=narration,
            message_id="visible-source",
            session_id=state.session_id,
            minute=480,
        )
        assert len(accepted) == len(proposals) and not rejected
        states["__manifest_snapshot__"] = {
            "original_manifest": {"clothing_settings": {"detailed": detailed}}
        }
        state.entity_states = states
        db.add(
            ChatMessage(
                id="visible-source",
                session_id=state.session_id,
                role="assistant",
                content=narration,
            )
        )
        await db.commit()


async def repair(db, state):
    identifier = next(iter(read(state.entity_states).conditions))
    states, accepted, rejected = apply(
        state.entity_states,
        [
            {
                "operation": "change",
                "condition_id": identifier,
                "detail": REPAIRED,
                "evidence": REPAIRED,
                "visual_detail": REPAIRED,
                "visual_region": "arms",
            }
        ],
        targets={"COAT"},
        item_targets={"COAT"},
        narration=REPAIRED,
        message_id="repair-source",
        session_id=state.session_id,
        minute=490,
    )
    assert accepted == [identifier] and not rejected
    state.entity_states = states
    db.add(
        ChatMessage(
            id="repair-source", session_id=state.session_id, role="assistant", content=REPAIRED
        )
    )
    await db.commit()


@pytest.mark.parametrize("detailed", [False, True])
async def test_current_garment_state_reaches_provider_and_does_not_mutate_ledger(
    auth_client, wardrobe, detailed
):
    await save_facts([fact()], detailed=detailed)
    async with TestSessionLocal() as db:
        state, _ = await subjects(db)
        before = read(state.entity_states).model_dump()
    result = await finish_job(auth_client, await start_job(auth_client))
    assert result["state"] == "succeeded", result
    assert TORN in wardrobe[0]["prompt"]
    assert "Red coat" in wardrobe[0]["prompt"]
    async with TestSessionLocal() as db:
        state, _ = await subjects(db)
        assert read(state.entity_states).model_dump() == before


async def test_only_confirmed_surface_reaches_provider_not_full_item_record(auth_client, wardrobe):
    nonvisual = "The lining contains a concealed serial number: HIDDEN_SERIAL_371."
    source = TORN + " " + nonvisual
    await save_facts([fact(detail=source, evidence=source)])
    result = await finish_job(auth_client, await start_job(auth_client))
    assert result["state"] == "succeeded", result
    assert TORN in wardrobe[0]["prompt"]
    assert "HIDDEN_SERIAL_371" not in wardrobe[0]["prompt"]


@pytest.mark.parametrize(
    "changes",
    [
        {"visibility": "private"},
        {"visual_detail": "", "visual_region": None},
        {"visual_detail": "An invented detail absent from the evidence"},
        {"target_id": "INNER", "visual_region": "torso"},
        {"target_id": "COAT", "visual_region": "head"},
        {"target_id": "OTHER_NPC", "kind": "injury", "part": "head", "visual_region": "head"},
    ],
)
async def test_hidden_unverified_or_other_subject_states_do_not_reach_provider(
    auth_client, wardrobe, changes
):
    await save_facts([fact(**changes)], detailed=True)
    result = await finish_job(auth_client, await start_job(auth_client))
    assert result["state"] == "succeeded", result
    assert TORN not in wardrobe[0]["prompt"]


@pytest.mark.parametrize("change", ["carried", "covered", "removed", "invalid_profile"])
async def test_current_clothing_controls_visibility_of_previous_item_state(
    auth_client, wardrobe, change
):
    await save_facts([fact()])
    async with TestSessionLocal() as db:
        state, npc = await subjects(db)
        if change == "carried":
            npc.visual_profile = {**PROFILE, "worn": [{"item_id": "INNER"}]}
        if change == "covered":
            npc.inventory = ["INNER", "COAT", "CAPE"]
            npc.visual_profile = {**PROFILE, "worn": [*PROFILE["worn"], {"item_id": "CAPE"}]}
        if change == "removed":
            overrides = deepcopy(state.entity_states)
            overrides["NPC_NEW"]["inventory"] = ["INNER"]
            state.entity_states = overrides
        if change == "invalid_profile":
            npc.visual_profile = {"version": 99}
        await db.commit()
    result = await finish_job(auth_client, await start_job(auth_client))
    assert result["state"] == "succeeded", result
    assert TORN not in wardrobe[0]["prompt"]


@pytest.mark.parametrize("change", ["edited", "unavailable_source"])
async def test_revoked_or_missing_source_does_not_become_an_image_fact(
    auth_client, wardrobe, change
):
    await save_facts([fact()])
    async with TestSessionLocal() as db:
        state, _ = await subjects(db)
        if change == "edited":
            retract(state, "visible-source")
        else:
            state.entity_states = remap(state.entity_states, {})
        assert next(iter(read(state.entity_states).conditions.values())).detail == TORN
        await db.commit()
    result = await finish_job(auth_client, await start_job(auth_client))
    assert result["state"] == "succeeded", result
    assert TORN not in wardrobe[0]["prompt"]


async def test_body_trace_is_bound_to_npc_and_hidden_by_current_clothing(auth_client, wardrobe):
    neck = "A small white bandage is visible on Lina's neck."
    covered = "A private marking is hidden on Lina's arm."
    await save_facts(
        [
            fact(
                target_id="NPC_NEW",
                kind="injury",
                part="neck",
                detail=neck,
                evidence=neck,
                visual_detail=neck,
                visual_region="head",
            ),
            fact(
                target_id="NPC_NEW",
                kind="injury",
                part="arm",
                detail=covered,
                evidence=covered,
                visual_detail=covered,
                visual_region="arms",
            ),
        ]
    )
    result = await finish_job(auth_client, await start_job(auth_client))
    assert result["state"] == "succeeded", result
    assert neck in wardrobe[0]["prompt"]
    assert covered not in wardrobe[0]["prompt"]


async def test_resolved_body_trace_is_not_in_portrait(auth_client, wardrobe):
    bandage = "A small white bandage is visible on Lina's forehead."
    await save_facts(
        [
            fact(
                target_id="NPC_NEW",
                kind="injury",
                part="head",
                detail=bandage,
                evidence=bandage,
                visual_detail=bandage,
                visual_region="head",
            )
        ]
    )
    async with TestSessionLocal() as db:
        state, _ = await subjects(db)
        identifier = next(iter(read(state.entity_states).conditions))
        healed = "The wound has healed and the bandage has been removed."
        state.entity_states, accepted, rejected = apply(
            state.entity_states,
            [{"operation": "heal", "condition_id": identifier, "evidence": healed}],
            targets={"NPC_NEW"},
            narration=healed,
            message_id="healed-source",
            session_id=state.session_id,
            minute=490,
        )
        assert accepted == [identifier] and not rejected
        await db.commit()
    result = await finish_job(auth_client, await start_job(auth_client))
    assert result["state"] == "succeeded", result
    assert bandage not in wardrobe[0]["prompt"]


async def test_new_portrait_uses_repaired_state_while_old_scene_keeps_torn_sleeve(
    auth_client, wardrobe
):
    await save_facts([fact()])
    async with TestSessionLocal() as db:
        state, npc = await subjects(db)
        avatar = await db.get(Avatar, "portrait-avatar")
        source = await db.get(ChatMessage, "visible-source")
        await capture_completed_moment(SimpleNamespace(db=db, state=state, avatar=avatar), source)
        frozen = deepcopy(registry_of(state.entity_states)["snapshots"][source.id])
        assert TORN in json.dumps(frozen["visible_facts"]["physical_conditions"])
        await repair(db, state)
        visible = await npc_visuals(db, state, npc)
        assert REPAIRED in json.dumps(visible)
        assert TORN not in json.dumps(visible)
    result = await finish_job(auth_client, await start_job(auth_client))
    assert result["state"] == "succeeded", result
    assert REPAIRED in wardrobe[0]["prompt"]
    assert TORN not in wardrobe[0]["prompt"]
    async with TestSessionLocal() as db:
        state, _ = await subjects(db)
        assert registry_of(state.entity_states)["snapshots"]["visible-source"] == frozen
