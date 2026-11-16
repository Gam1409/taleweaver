"""Terminal chapter rewards and canonical session status survive retries and reloads."""

import asyncio
import json
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.gameplay.sequence_progress import evaluate_sequence_progress
from backend.engine.scripting.context import ScriptChangeset
from backend.models import (
    AdventureTemplate,
    Avatar,
    ChatMessage,
    GameSession,
    SessionState,
    User,
    WorldScene,
)
from tests.conftest import TestSessionLocal

SID = "terminal-session"
FINAL = {
    "id": "FINALE",
    "order": 1,
    "title": "Finale",
    "required_item_id": "TOKEN",
    "exp_reward": 10,
}


@pytest_asyncio.fixture
async def terminal_world(auth_client, monkeypatch):
    monkeypatch.setattr(
        "backend.engine.gameplay.manager.GameMasterLLM.for_role",
        Mock(side_effect=AssertionError("Terminal regression must not request inference")),
    )
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        adventure = AdventureTemplate(
            id="terminal-template",
            owner_id=user.id,
            title="Terminal story",
            time_per_turn=7,
            rule_enforcement_mode="rpg",
            strict_rules=True,
            sequences=[deepcopy(FINAL)],
            original_manifest={"sequences": [deepcopy(FINAL)]},
        )
        db.add(adventure)
        await db.flush()
        avatar = Avatar(
            id="terminal-avatar",
            user_id=user.id,
            name="Hero",
            hp=100,
            max_hp=100,
            stamina=50,
            max_stamina=50,
            mana=50,
            max_mana=50,
            inventory=[{"id": "TOKEN", "name": "Token"}],
            status_effects=[],
        )
        db.add(avatar)
        await db.flush()
        db.add(
            GameSession(
                id=SID,
                user_id=user.id,
                avatar_id=avatar.id,
                template_id=adventure.id,
                adventure_title=adventure.title,
            )
        )
        await db.flush()
        db.add(
            SessionState(
                session_id=SID,
                user_id=user.id,
                avatar_id=avatar.id,
                template_id=adventure.id,
                current_scene_id="START",
                active_sequence_id="FINALE",
                active_sequence_order=1,
            )
        )
        db.add_all(
            [
                WorldScene(id=scene, session_id=SID, label=scene, description="A room.")
                for scene in ("START", "NEXT")
            ]
        )
        await db.commit()
    return SID


async def context(db, session_id=SID):
    session = await db.get(GameSession, session_id)
    state = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
    avatar = await db.get(Avatar, session.avatar_id)
    user = await db.get(User, session.user_id)
    return session, state, avatar, user


def final_payload(response):
    blocks = response.text.split("\n\n")
    finals = [block for block in blocks if "event: final\n" in block]
    assert finals, response.text
    return json.loads(
        next(line[6:] for line in finals[-1].splitlines() if line.startswith("data: "))
    )


async def inventory(client, session_id=SID):
    response = await client.post(
        f"/api/adventures/{session_id}/chat", json={"content": "/inventory"}
    )
    assert response.status_code == 200, response.text
    return final_payload(response)


async def assert_terminal_once(session_id=SID, expected_xp=10):
    async with TestSessionLocal() as db:
        session, state, avatar, user = await context(db, session_id)
        assert avatar.exp == expected_xp
        assert state.is_completed is True and session.status == "completed"
        assert len([entry for entry in user.game_log if entry["session_id"] == SID]) == 1
        assert not user.earned_awards
        messages = list(
            await db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id))
        )
        assert (
            len(
                [
                    message
                    for message in messages
                    if message.content == "Sequence completed: Finale (+10 XP)"
                ]
            )
            == 1
        )
        return deepcopy(user.game_log)


@pytest.mark.asyncio
async def test_inventory_final_chapter_rewards_and_finalizes_exactly_once(
    auth_client, terminal_world
):
    first = await inventory(auth_client)
    assert first["game_completed"] is True and first["game_over"] is False
    assert first["pending_terminal_epilogue"] is True
    original_log = await assert_terminal_once()
    for _ in range(2):
        repeated = await inventory(auth_client)
        assert repeated["game_completed"] is True
        assert repeated["pending_terminal_epilogue"] is True
        assert await assert_terminal_once() == original_log


@pytest.mark.asyncio
async def test_concurrent_inventory_writer_retries_do_not_duplicate_terminal_rewards(
    auth_client, terminal_world, monkeypatch
):
    entered, release = asyncio.Event(), asyncio.Event()
    original = GameTurnManager.initialize

    async def hold_first(manager):
        if manager.game_id == SID and not entered.is_set():
            entered.set()
            await release.wait()
        return await original(manager)

    monkeypatch.setattr(GameTurnManager, "initialize", hold_first)
    first = asyncio.create_task(inventory(auth_client))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        blocked = await auth_client.post(
            f"/api/adventures/{SID}/chat", json={"content": "/inventory"}
        )
        assert "This session is busy" in blocked.text
    finally:
        release.set()
    await asyncio.wait_for(first, 5)
    await inventory(auth_client)
    await assert_terminal_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,has_token", [("vn", True), ("rpg", False)])
async def test_inventory_without_permitted_completed_progress_keeps_session_active(
    auth_client, terminal_world, mode, has_token
):
    async with TestSessionLocal() as db:
        session, state, avatar, _ = await context(db)
        adventure = await db.get(AdventureTemplate, session.template_id)
        adventure.rule_enforcement_mode = mode
        avatar.inventory = [{"id": "TOKEN", "name": "Token"}] if has_token else []
        await db.commit()
    result = await inventory(auth_client)
    assert result["game_completed"] is False
    async with TestSessionLocal() as db:
        session, state, avatar, user = await context(db)
        assert session.status == "active" and state.is_completed is False and avatar.exp == 0
        assert not user.game_log


@pytest.mark.asyncio
async def test_already_completed_state_finalizes_without_reconstructing_reward(
    auth_client, terminal_world
):
    async with TestSessionLocal() as db:
        _, state, avatar, _ = await context(db)
        state.is_completed, avatar.exp = True, 123
        await db.commit()
    await inventory(auth_client)
    async with TestSessionLocal() as db:
        session, state, avatar, user = await context(db)
        assert session.status == "completed" and state.is_completed is True and avatar.exp == 123
        assert len(user.game_log) == 1


@pytest.mark.asyncio
async def test_completed_evaluator_and_script_completion_cannot_repeat_final_reward(terminal_world):
    async with TestSessionLocal() as db:
        session, state, avatar, user = await context(db)
        manager = GameTurnManager(db, SID, user)
        assert await manager.initialize()
        await manager._apply_script_changeset(ScriptChangeset(sequence_completed=True))
        await db.commit()
        assert avatar.exp == 10 and session.status == "completed"
        assert (
            evaluate_sequence_progress(manager.adventure, state, avatar, force_complete=True) == []
        )
        await manager._apply_script_changeset(ScriptChangeset(sequence_completed=True))
        await db.commit()
        assert avatar.exp == 10


@pytest.mark.asyncio
async def test_completed_copy_and_ads_import_keep_terminal_reward_stable(
    auth_client, terminal_world
):
    await inventory(auth_client)
    copied = await auth_client.post(f"/api/adventures/sessions/{SID}/copy")
    assert copied.status_code == 201, copied.text
    exported = await auth_client.get(f"/api/adventures/sessions/{SID}/export")
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("terminal.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    for session_id in (copied.json()["game_id"], imported.json()["game_id"]):
        result = await inventory(auth_client, session_id)
        assert result["game_completed"] is True
        async with TestSessionLocal() as db:
            session, state, avatar, _ = await context(db, session_id)
            assert session.status == "completed" and state.is_completed is True and avatar.exp == 10


@pytest.mark.asyncio
async def test_reentrant_final_sequence_end_script_awards_and_announces_once(terminal_world):
    async with TestSessionLocal() as db:
        session, _, avatar, user = await context(db)
        adventure = await db.get(AdventureTemplate, session.template_id)
        adventure.sequences = [
            FINAL
            | {
                "on_end_sequence_script": "if not tw.vars.get('ended_once'):\n"
                "    tw.vars.set('ended_once', True)\n"
                "    tw.sequences.complete_current()"
            }
        ]
        manager = GameTurnManager(db, SID, user)
        assert await manager.initialize()
        await manager._apply_script_changeset(ScriptChangeset(sequence_completed=True))
        await db.commit()
        await assert_terminal_once()
        assert avatar.exp == 10


@pytest.mark.asyncio
async def test_next_chapter_start_script_may_complete_the_newly_advanced_chapter(terminal_world):
    async with TestSessionLocal() as db:
        session, state, avatar, user = await context(db)
        adventure = await db.get(AdventureTemplate, session.template_id)
        adventure.sequences = [
            {"id": "FIRST", "order": 1, "title": "First", "exp_reward": 5},
            FINAL | {"order": 2, "on_start_sequence_script": "tw.sequences.complete_current()"},
        ]
        state.active_sequence_id = "FIRST"
        manager = GameTurnManager(db, SID, user)
        assert await manager.initialize()
        await manager._apply_script_changeset(ScriptChangeset(sequence_completed=True))
        await db.commit()
        assert state.active_sequence_id == "FINALE" and session.status == "completed"
        assert avatar.exp == 15
        messages = list(
            await db.scalars(select(ChatMessage.content).where(ChatMessage.session_id == SID))
        )
        assert messages.count("Sequence completed: First (+5 XP)") == 1
        assert messages.count("Sequence completed: Finale (+10 XP)") == 1
        assert len(user.game_log) == 1


@pytest.mark.asyncio
async def test_cancelled_end_hook_can_retry_without_a_stuck_completion_guard(terminal_world):
    async with TestSessionLocal() as db:
        session, state, avatar, user = await context(db)
        adventure = await db.get(AdventureTemplate, session.template_id)
        adventure.sequences = [FINAL | {"on_end_sequence_script": "tw.vars.set('ended', True)"}]
        manager = GameTurnManager(db, SID, user)
        assert await manager.initialize()
        original = manager._execute_inline_script
        manager._execute_inline_script = AsyncMock(side_effect=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await manager._apply_script_changeset(ScriptChangeset(sequence_completed=True))
        assert avatar.exp == 0 and state.is_completed is False and session.status == "active"
        manager._execute_inline_script = original
        await manager._apply_script_changeset(ScriptChangeset(sequence_completed=True))
        await db.commit()
        await assert_terminal_once()


@pytest.mark.asyncio
async def test_first_explicit_completion_and_chapter_completion_keep_existing_reward(
    terminal_world,
):
    async with TestSessionLocal() as db:
        _, _, _, user = await context(db)
        manager = GameTurnManager(db, SID, user)
        assert await manager.initialize()
        await manager._apply_script_changeset(
            ScriptChangeset(game_completed=True, sequence_completed=True)
        )
        await db.commit()
        await assert_terminal_once()
