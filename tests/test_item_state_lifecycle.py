"""Item facts survive actual turns, reload, transfer, replay, copy and import."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.gameplay.session_sheet import build_sheet_snapshot
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.ledger import apply, read
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_item_state_identity import record
from tests.test_session_authored_fields import TEMPLATE, seed_template
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn

ITEM = dict(id="flask", name="Flask", description="An empty metal flask.", image_url="/flask.png")


class ItemRoles(TurnRoles):
    proposals = []
    actions = []

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if issubclass(schema, ItemExtraction):
            self.calls.append((schema.__name__, args, kwargs))
            return extraction(schema, condition_updates=self.proposals, actions=self.actions)
        return await super().structured(*args, **kwargs)


@pytest.mark.asyncio
async def test_real_turn_player_source_reload_transfer_and_replay(monkeypatch):
    narration = "You check the flask and confirm that."
    report = "The flask is half full."
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", narration)
    roles = ItemRoles()
    roles.proposals = [{**record(report, player_evidence=report), "evidence": narration}]
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        avatar.inventory = [deepcopy(ITEM)]
        await db.commit()
        events = [
            event async for event in GameTurnManager(db, "session-1", user).process_turn(report)
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        row = next(iter(read(state.entity_states).conditions.values()))
        assert row.target_id == ITEM["id"] and row.reported_by.kind == "player"
        player = await db.get(ChatMessage, row.reported_by.message_id)
        assert player.role == "user" and player.content == report
        assert avatar.inventory == [ITEM]
        sheet = await build_sheet_snapshot(avatar, state, db)
        assert sheet["inventory"][0]["current_state"][0]["detail"] == report
        assert len(roles.calls) == 3
        state_id, avatar_id, first_id = state.id, avatar.id, row.id
    roles.proposals = []
    transfer = "You hand the flask to Lina."
    roles.actions = [
        dict(
            item_id="flask",
            source_owner="__player__",
            destination_owner="LINA",
            disposition="carried",
            basis="completed",
            evidence=transfer,
        )
    ]
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", transfer)
    async with TestSessionLocal() as db:
        user = await db.merge(user)
        events = [
            event
            async for event in GameTurnManager(db, "session-1", user).process_turn(
                "Give Lina the flask."
            )
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        state, avatar = await db.get(SessionState, state_id), await db.get(Avatar, avatar_id)
        assert not avatar.inventory
        assert [
            item for item in state.entity_states["LINA"]["inventory"] if item["id"] == "flask"
        ] == [ITEM]
        assert any(item["id"] == "HIDDEN_RING" for item in state.entity_states["LINA"]["inventory"])
        assert read(state.entity_states).conditions[first_id].detail == report
        assert report in json.dumps(roles.prompts[-1], ensure_ascii=False, default=str)
        roles.actions = []
        reply = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == "session-1", ChatMessage.content == transfer
            )
        )
        events = [
            event
            async for event in GameTurnManager(db, "session-1", user).process_turn(
                "ignored", replay_message_id=reply.id
            )
        ]
        assert final_payload(events)["status"] == "success"
        await db.refresh(avatar)
        await db.refresh(state)
        assert avatar.inventory == [ITEM]  # Replay restores ownership and the same item state.
        assert read(state.entity_states).conditions[first_id].detail == report


@pytest.mark.asyncio
async def test_copy_export_import_keep_item_id_and_both_source_messages(
    auth_client, monkeypatch, tmp_path
):
    await seed_template(monkeypatch, tmp_path, "vn", "template")
    response = await auth_client.post(f"/api/adventures/{TEMPLATE}/sessions/start")
    assert response.status_code == 201
    session_id = response.json()["game_id"]
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
        avatar = await db.get(Avatar, state.avatar_id)
        avatar.inventory = [{**ITEM, "image_url": None}]
        player = ChatMessage(session_id=session_id, role="user", content="The flask is half full.")
        reply = ChatMessage(
            session_id=session_id, role="assistant", content="You confirm the remaining water."
        )
        db.add_all([player, reply])
        await db.flush()
        state.entity_states, _, errors = apply(
            state.entity_states,
            [{**record(player.content, player_evidence=player.content), "evidence": reply.content}],
            targets={"flask"},
            item_targets={"flask"},
            narration=reply.content,
            message_id=reply.id,
            player_message=(player.id, player.content),
            session_id=session_id,
            minute=42,
        )
        assert not errors
        await db.commit()
    copied = await auth_client.post(f"/api/adventures/sessions/{session_id}/copy")
    assert copied.status_code == 201, copied.text
    exported = await auth_client.get(f"/api/adventures/sessions/{copied.json()['game_id']}/export")
    assert exported.status_code == 200
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("items.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    for identifier in [copied.json()["game_id"], imported.json()["game_id"]]:
        async with TestSessionLocal() as db:
            state = await db.scalar(
                select(SessionState).where(SessionState.session_id == identifier)
            )
            avatar = await db.get(Avatar, state.avatar_id)
            row = next(iter(read(state.entity_states).conditions.values()))
            assert avatar.inventory[0]["id"] == row.target_id == "flask"
            assert row.first_recorded_minute == row.last_changed_minute == 42
            for source in [
                row.latest,
                row.reported_by,
                read(state.entity_states).events[0].reported_by,
            ]:
                message = await db.get(ChatMessage, source.message_id)
                assert message.session_id == identifier and source.quote in message.content
