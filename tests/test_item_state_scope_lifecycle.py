"""State visibility, possession authority and saved-item lifecycle stay independent."""

import json
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.command_parser import CommandParser
from backend.engine.gameplay.session_sheet import build_sheet_snapshot
from backend.engine.gameplay.turn_llm_pipeline import TurnLlmContextBuilder
from backend.engine.physical_conditions.debug import command
from backend.engine.physical_conditions.item_state import project
from backend.engine.physical_conditions.ledger import apply, read
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_item_state_identity import record
from tests.test_item_state_lifecycle import ITEM, ItemRoles
from tests.test_session_authored_fields import TEMPLATE, seed_template
from tests.test_vn_turn_integration import final_payload, install_roles, seed_vn


@pytest.mark.asyncio
async def test_fixed_item_state_does_not_make_the_object_transferable(monkeypatch):
    fact = "The fixed desk is dusty."
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", fact)
    roles = ItemRoles()
    roles.proposals = [record(fact, "cleanliness", "DESK")]
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        before = deepcopy(avatar.inventory)
        desk = WorldEntity(
            id="DESK",
            session_id=state.session_id,
            entity_type="OBJECT",
            name="Fixed desk",
            description="A desk bolted to the floor.",
            current_scene_id="START",
            is_portable=False,
            is_hidden=False,
            is_in_inventory=False,
        )
        db.add(desk)
        await db.commit()
        events = [
            event
            async for event in GameTurnManager(db, "session-1", user).process_turn(
                "Examine the desk."
            )
        ]
        assert final_payload(events)["status"] == "success"
        await db.refresh(state)
        ledger = read(state.entity_states)
        row = next((row for row in ledger.conditions.values() if row.target_id == "DESK"), None)
        assert row is not None, ledger.last_check
        assert row.detail == fact
        recorded = row.model_dump()
        transfer = "You lift the fixed desk."
        monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", transfer)
        roles.proposals = []
        roles.actions = [
            dict(
                item_id="DESK",
                source_owner="__scene__",
                destination_owner="__player__",
                disposition="carried",
                basis="completed",
                evidence=transfer,
            )
        ]
        events = [
            event
            async for event in GameTurnManager(db, "session-1", user).process_turn(
                "Try to carry the fixed desk."
            )
        ]
        assert final_payload(events)["status"] == "success"
        await db.refresh(avatar)
        await db.refresh(state)
        await db.refresh(desk)
        assert avatar.inventory == before
        assert desk.current_scene_id == "START" and desk.is_in_inventory is False
        assert not (state.entity_states.get("DESK") or {}).get("is_in_inventory")
        assert read(state.entity_states).conditions[row.id].model_dump() == recorded
        assert not state.entity_states["__narrated_items__"]["accepted"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "placement,canonical",
    [
        ("open", False),
        ("closed", False),
        ("hidden", False),
        ("offscene", False),
        ("npc", False),
        ("held_open", False),
        ("held_closed", False),
        ("held_open", True),
        ("held_closed", True),
        ("nested_held", True),
    ],
)
async def test_real_narrator_receives_only_accessible_public_container_item_facts(
    monkeypatch, placement, canonical
):
    fact, secret = "The flask is half full.", "The flask bears a private inscription."
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", "The room is quiet.")
    roles = ItemRoles()
    roles.proposals = []
    install_roles(monkeypatch, roles)
    blocks = []
    original = TurnLlmContextBuilder._build_state_blocks

    def capture(builder, *args, **kwargs):
        result = original(builder, *args, **kwargs)
        blocks.append(result[1])
        return result

    monkeypatch.setattr(TurnLlmContextBuilder, "_build_state_blocks", capture)
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        before_inventory = await _seed_container_possessions(
            db, state, avatar, placement, canonical
        )
        source = ChatMessage(
            session_id=state.session_id, role="assistant", content=fact + " " + secret
        )
        db.add(source)
        await db.flush()
        state.entity_states, _, errors = apply(
            state.entity_states,
            [record(fact), {**record(secret, "inscription"), "visibility": "private"}],
            targets={"flask"},
            item_targets={"flask"},
            narration=source.content,
            message_id=source.id,
            session_id=state.session_id,
            minute=11,
        )
        assert not errors
        await db.commit()
        events = [
            event
            async for event in GameTurnManager(db, "session-1", user).process_turn(
                "Look around the room."
            )
        ]
        assert final_payload(events)["status"] == "success"
        persistent = (
            blocks[-1]
            .partition("PERSISTENT PHYSICAL CONDITIONS (current saved facts):")[2]
            .partition("Omission from recent prose")[0]
        )
        assert (fact in persistent) is (placement in {"open", "held_open"}), persistent
        assert secret not in persistent
        await db.refresh(state)
        assert len(read(state.entity_states).conditions) == 2
        assert all(
            row.first_recorded_minute == row.last_changed_minute == 11
            for row in read(state.entity_states).conditions.values()
        )
        assert avatar.inventory == before_inventory


@pytest.mark.asyncio
async def test_equipment_manual_correction_survives_reload_copy_and_archive(
    auth_client, monkeypatch, tmp_path
):
    await seed_template(monkeypatch, tmp_path, "vn", "template")
    started = await auth_client.post(f"/api/adventures/{TEMPLATE}/sessions/start")
    assert started.status_code == 201
    session_id = started.json()["game_id"]
    coat = dict(
        id="COAT",
        name="Travel coat",
        description="A canvas travel coat.",
        image_url=None,
        item_type="WEARABLE",
        slot="Chest",
        wearable_slots=["Chest"],
    )
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
        avatar = await db.get(Avatar, state.avatar_id)
        avatar.inventory = [deepcopy(coat)]
        avatar.equipment = {}
        assert "Equipped Travel coat" in CommandParser._handle_equip(avatar, "Travel coat")
        assert avatar.inventory == []
        report = "The coat is damp."
        player = ChatMessage(session_id=session_id, role="user", content=report)
        reply = ChatMessage(
            session_id=session_id,
            role="assistant",
            content="You check the coat and confirm the damp fabric.",
        )
        db.add_all([player, reply])
        await db.flush()
        state.entity_states, ids, errors = apply(
            state.entity_states,
            [
                {
                    **record(report, "wetness", "COAT", player_evidence=report),
                    "evidence": reply.content,
                    "visibility": "private",
                }
            ],
            targets={"COAT"},
            item_targets={"COAT"},
            narration=reply.content,
            message_id=reply.id,
            player_message=(player.id, report),
            session_id=session_id,
            minute=12,
        )
        assert not errors
        state.is_debug_enabled = True
        state.in_game_time = 30
        correction = dict(
            operation="change", condition_id=ids[0], detail="The coat is dry.", expected_revision=1
        )
        assert (
            await command(db, state, "condition " + json.dumps(correction), avatar=avatar)
        ).startswith("DEBUG: Updated")
        assert state.in_game_time == 30
        state.in_game_time = 60
        correction["expected_revision"] = 2
        assert (
            await command(db, state, "condition " + json.dumps(correction), avatar=avatar)
        ).startswith("DEBUG: Updated")
        assert state.in_game_time == 60
        await db.commit()
    copied = await auth_client.post(f"/api/adventures/sessions/{session_id}/copy")
    assert copied.status_code == 201, copied.text
    copy_id = copied.json()["game_id"]
    exported = await auth_client.get(f"/api/adventures/sessions/{copy_id}/export")
    assert exported.status_code == 200, exported.text
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("equipped.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    for identifier in [session_id, copy_id, imported.json()["game_id"]]:
        async with TestSessionLocal() as db:
            await _assert_saved_coat(db, identifier, coat, ids[0])


async def _assert_saved_coat(db, identifier, coat, condition_id):
    state = await db.scalar(select(SessionState).where(SessionState.session_id == identifier))
    avatar = await db.get(Avatar, state.avatar_id)
    ledger = read(state.entity_states)
    row = ledger.conditions[condition_id]
    assert row.target_id == "COAT" and row.detail == "The coat is dry."
    assert row.first_recorded_minute == 12 and row.last_changed_minute == 30
    assert state.in_game_time == 60
    assert row.visibility == "private" and row.latest.kind == "manual"
    assert [(event.minute, event.detail) for event in ledger.events] == [
        (12, "The coat is damp."),
        (30, "The coat is dry."),
        (60, "The coat is dry."),
    ]
    assert avatar.inventory == [] and [item for item in avatar.equipment.values() if item] == [coat]
    assert "current_state" not in project([coat], state.entity_states)[0]
    sheet = await build_sheet_snapshot(avatar, state, db)
    assert sheet["equipment"]["Chest"]["current_state"][0]["detail"] == row.detail
    for source, role in [(row.origin, "assistant"), (ledger.events[0].reported_by, "user")]:
        message = await db.get(ChatMessage, source.message_id)
        assert message.session_id == identifier and message.role == role
        assert source.quote in message.content
        assert source.content_hash == sha256(message.content.encode()).hexdigest()


async def _seed_container_possessions(db, state, avatar, placement, canonical):
    item = {**ITEM, "image_url": None}
    held = placement.startswith("held_") or placement == "nested_held"
    if held:
        avatar.inventory = [dict(id="BOX", name="Archive box", item_type="CONTAINER")]
    before_inventory = deepcopy(avatar.inventory)
    box = WorldEntity(
        id="BOX",
        session_id=state.session_id,
        entity_type="OBJECT",
        name="Archive box",
        description="A box for archive supplies.",
        current_scene_id="FOREST" if placement == "offscene" else "START",
        item_type="CONTAINER",
        is_portable=held,
        is_hidden=placement == "hidden",
        is_in_inventory=held,
        metadata_json={"locked": placement in {"closed", "held_closed"}},
        inventory=[]
        if placement == "npc"
        else ["INNER"]
        if placement == "nested_held"
        else ["flask"]
        if canonical
        else [item],
    )
    db.add(box)
    rows = [box]
    if placement == "nested_held":
        inner = WorldEntity(
            id="INNER",
            session_id=state.session_id,
            entity_type="OBJECT",
            name="Inner box",
            description="An open box inside the carried box.",
            current_scene_id="START",
            item_type="CONTAINER",
            is_portable=True,
            is_hidden=False,
            is_in_inventory=False,
            metadata_json={"locked": False},
            inventory=["flask"],
        )
        db.add(inner)
        rows.append(inner)
    if canonical:
        child = WorldEntity(
            id="flask",
            session_id=state.session_id,
            entity_type="OBJECT",
            name="Flask",
            description="A metal flask.",
            current_scene_id="START",
            is_portable=True,
            is_hidden=False,
            is_in_inventory=False,
        )
        db.add(child)
        rows.append(child)
    if held:
        snapshot = possession_snapshot(SimpleNamespace(avatar=avatar, state=state), rows)
        assert snapshot.owners["BOX"] == "__player__"
        if placement == "held_open":
            assert snapshot.owners["flask"] == "BOX"
        else:
            assert "flask" not in snapshot.items
    if placement == "npc":
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.id == "LINA"
            )
        )
        npc.inventory = [item]
    return before_inventory
