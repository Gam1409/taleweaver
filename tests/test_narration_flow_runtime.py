"""Narration guidance follows existing message windows and model-call boundaries."""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.chpm import inference, rendering
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY as CHPM_KEY
from backend.engine.gameplay import turn_prompt_layout
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrator.history import completed_narrations
from backend.engine.narrator.settings import SETTINGS_KEY
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_chpm_turn import ChpmRoles
from tests.test_narration_memory import _seed_context
from tests.test_vn_turn_integration import (
    ACTION,
    NARRATION,
    PRIOR,
    TurnRoles,
    install_roles,
    seed_vn,
)

ADVISORY = "NARRATION FLOW CHECK: Vary the opening when the scene permits it."


def test_only_current_completed_session_narrations_are_style_evidence():
    def row(content, **fields):
        return SimpleNamespace(session_id="session", role="assistant", content=content, **fields)

    rows = [
        row("Current canonical prose.", versions=[{"content": "Archived prose."}]),
        row("Debug narration.", is_debug=True),
        row("Interrupted fragment.", npc_journal={"status": "incomplete"}),
        row("  "),
        row(
            "Completed prose with a failed background extraction.", npc_journal={"status": "failed"}
        ),
        SimpleNamespace(session_id="foreign", role="assistant", content="Foreign prose."),
        SimpleNamespace(session_id="session", role="user", content="Player instruction."),
        SimpleNamespace(session_id="session", role="system", content="A game event."),
    ]
    assert completed_narrations(rows, "session") == [
        "Current canonical prose.",
        "Completed prose with a failed background extraction.",
    ]


@pytest.mark.asyncio
async def test_dynamic_suffix_reuses_loaded_memory_without_changing_user_state_or_queries(
    monkeypatch,
):
    observed = []

    def guidance(state, narrations, *, language=None):
        observed.append((list(narrations), language))
        return ADVISORY

    monkeypatch.setattr(turn_prompt_layout, "flow_guidance", guidance)
    async with TestSessionLocal() as db:
        user, adventure, avatar, state = await _seed_context(db, max_memory_turns_state=10)
        state.entity_states = {SETTINGS_KEY: {"flow": "gentle"}, "retained": {"value": 7}}
        records = [
            ("u0", "user", "Begin.", {}),
            ("a0", "assistant", "A completed scene.", {}),
            ("u1", "user", "Inspect.", {}),
            ("a1", "assistant", "A debug reply.", {"is_debug": True}),
            ("u2", "user", "Wait.", {}),
            (
                "a2",
                "assistant",
                "An interrupted fragment.",
                {"npc_journal": {"status": "incomplete"}},
            ),
            ("u3", "user", "Listen.", {}),
            (
                "a3",
                "assistant",
                "The current canonical ending.",
                {"versions": [{"content": "Old revision."}]},
            ),
            ("current", "user", "Current action", {}),
        ]
        for index, (identifier, role, content, fields) in enumerate(records):
            db.add(
                ChatMessage(
                    id=identifier,
                    session_id=state.session_id,
                    role=role,
                    content=content,
                    created_at=datetime(2026, 1, 1) + timedelta(seconds=index),
                    **fields,
                )
            )
        await db.commit()
        before = deepcopy(state.entity_states)
        execute = db.execute
        queries = []

        async def counted(*args, **kwargs):
            queries.append(args[0])
            return await execute(*args, **kwargs)

        monkeypatch.setattr(db, "execute", counted)
        manager = GameTurnManager(
            db, state.session_id, user, state=state, adventure=adventure, avatar=avatar
        )
        manager.turn_language = "Arabic"
        messages, turns = await manager._build_narration_messages(
            "Stable policy", "Current action", "Committed state"
        )
        assert len(queries) == 2  # The existing marker and memory-window reads only.
        assert observed == [(["A completed scene.", "The current canonical ending."], "Arabic")]
        assert messages[0] == {"role": "system", "content": "Stable policy\n\n" + ADVISORY}
        assert messages[-1] == {
            "role": "user",
            "content": "Committed state\n\nPLAYER ACTION:\nCurrent action",
        }
        assert turns == 10 and state.entity_states == before
        assert "Old revision." not in str(messages)


@pytest.mark.asyncio
async def test_disabled_flow_keeps_original_message_contract():
    async with TestSessionLocal() as db:
        user, adventure, avatar, state = await _seed_context(db)
        state.entity_states = {SETTINGS_KEY: {"flow": "off"}}
        db.add(ChatMessage(session_id=state.session_id, role="user", content="Continue."))
        await db.commit()
        manager = GameTurnManager(
            db, state.session_id, user, state=state, adventure=adventure, avatar=avatar
        )
        messages, _ = await manager._build_narration_messages("Stable policy", "Continue.")
        assert messages == [
            {"role": "system", "content": "Stable policy"},
            {"role": "user", "content": "Continue."},
        ]


class RepairRoles(ChpmRoles):
    def __init__(self):
        super().__init__()
        self.reviews = 0
        self.repair_system = ""

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") == "validation":
            self.reject = self.reviews == 0
            self.reviews += 1
        if kwargs.get("phase") == "repair":
            self.repair_system = system
        return await super().simple(system, payload, model, **kwargs)


@pytest.mark.parametrize("buffered", [False, True])
@pytest.mark.asyncio
async def test_real_turn_hands_same_suffix_to_stream_and_existing_buffered_repair(
    monkeypatch, buffered
):
    inputs = []

    def guidance(_state, narrations, *, language=None):
        inputs.append((list(narrations), language))
        return ADVISORY

    monkeypatch.setattr(turn_prompt_layout, "flow_guidance", guidance)
    roles = RepairRoles() if buffered else TurnRoles()
    install_roles(monkeypatch, roles)
    if buffered:
        monkeypatch.setattr(inference, "GameMasterLLM", roles)
        monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, prior_id = await seed_vn(db)
        prior = await db.get(ChatMessage, prior_id)
        db.add(
            ChatMessage(
                session_id=state.session_id,
                role="user",
                content="We repair the shelf.",
                created_at=prior.created_at - timedelta(seconds=1),
            )
        )
        state.entity_states = {
            **state.entity_states,
            SETTINGS_KEY: {"verbosity": "terse", "flow": "gentle"},
        }
        if buffered:
            state.entity_states = {
                **state.entity_states,
                CHPM_KEY: KernelState(
                    settings=Settings(mode="live", actor_ids=["LINA"], failure_policy="strict")
                ).model_dump(),
            }
        await db.commit()
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(ACTION)
        ]
        assert not any(event.startswith("event: error") for event in events), "".join(events)
        assert any(event.startswith("event: final") for event in events)
        assert inputs == [([PRIOR], "Russian")]
        assert len(roles.prompts) == 1
        args, kwargs = roles.prompts[0]
        assert args[0] == kwargs["messages"][0]["content"]
        assert args[0].count(ADVISORY) == 1
        assert "normally one or two short narration sentences" in args[0]
        replies = list(
            await db.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == state.session_id, ChatMessage.role == "assistant"
                )
            )
        )
        assert len(replies) == 2 and replies[-1].content == NARRATION
        if buffered:
            assert roles.repair_system.count(ADVISORY) == 1
            assert roles.chpm_calls.count("repair") == 1
            assert len(roles.chpm_calls) == 5
        else:
            assert len(roles.calls) == 3


@pytest.mark.asyncio
async def test_replay_reuses_current_branch_without_old_candidate_or_duplicate_suffix(monkeypatch):
    observed = []

    def guidance(_state, narrations, *, language=None):
        observed.append(list(narrations))
        return ADVISORY

    monkeypatch.setattr(turn_prompt_layout, "flow_guidance", guidance)
    roles = TurnRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, prior_id = await seed_vn(db)
        prior = await db.get(ChatMessage, prior_id)
        db.add(
            ChatMessage(
                session_id=state.session_id,
                role="user",
                content="We repair the shelf.",
                created_at=prior.created_at - timedelta(seconds=1),
            )
        )
        await db.commit()
        first = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(ACTION)
        ]
        assert any(event.startswith("event: final") for event in first)
        reply = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == state.session_id,
                ChatMessage.role == "assistant",
                ChatMessage.id != prior_id,
            )
        )
        original_id = reply.id
        minute = state.in_game_time
        second = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                "Ignored replay input", replay_message_id=original_id
            )
        ]
        assert any(event.startswith("event: final") for event in second), "".join(second)
        assert observed == [[PRIOR], [PRIOR]]
        assert await db.get(ChatMessage, original_id) is None
        assert state.in_game_time == minute
        assert len(roles.prompts) == 2 and len(roles.calls) == 6
        assert all(args[0].count(ADVISORY) == 1 for args, _kwargs in roles.prompts)


@pytest.mark.asyncio
async def test_actual_exit_traversal_uses_shared_guidance_without_replacing_arrival_context(
    monkeypatch,
):
    monkeypatch.setattr(turn_prompt_layout, "flow_guidance", lambda *_args, **_kwargs: ADVISORY)
    roles = TurnRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        db.add(
            WorldScene(
                id="HARBOUR",
                session_id=state.session_id,
                label="Harbour",
                description="A quiet coastal quay.",
            )
        )
        db.add(
            WorldExit(
                id="COAST_PATH",
                session_id=state.session_id,
                from_scene_id="START",
                to_scene_id="HARBOUR",
                label="Coastal path",
                exit_type="one_way",
                is_locked=False,
            )
        )
        await db.commit()
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                "/traverse_exit COAST_PATH"
            )
        ]
        assert not any(event.startswith("event: error") for event in events), "".join(events)
        assert any(event.startswith("event: scene_transition") for event in events)
        assert state.current_scene_id == "HARBOUR"
        assert len(roles.prompts) == 1
        args, kwargs = roles.prompts[0]
        assert args[0] == kwargs["messages"][0]["content"]
        assert args[0].count(ADVISORY) == 1
        assert "[SCENE_TRANSITION]" in kwargs["messages"][-1]["content"]
        assert "Harbour" in kwargs["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_narration_only_pickup_keeps_its_bounded_reaction_and_single_narrator(monkeypatch):
    monkeypatch.setattr(turn_prompt_layout, "flow_guidance", lambda *_args, **_kwargs: ADVISORY)
    roles = TurnRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        db.add(
            WorldEntity(
                id="LETTER",
                session_id=state.session_id,
                entity_type="OBJECT",
                name="Sealed letter",
                description="A letter on the archive table.",
                current_scene_id="START",
                is_portable=True,
                metadata_json={
                    "pickup_trigger": {"mode": "narration", "cue": "A paper edge rustles."}
                },
            )
        )
        await db.commit()
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                "/take_direct LETTER"
            )
        ]
        assert not any(event.startswith("event: error") for event in events), "".join(events)
        assert any(event.startswith("event: final") for event in events)
        assert len(roles.prompts) == 1
        args, kwargs = roles.prompts[0]
        assert args[0] == kwargs["messages"][0]["content"]
        assert args[0].count(ADVISORY) == 1
        assert "[ITEM_PICKUP]" in kwargs["messages"][-1]["content"]
        assert "A paper edge rustles." in kwargs["messages"][-1]["content"]
        assert all(call[0].startswith("ItemExtraction") for call in roles.calls)
        await db.refresh(avatar)
        assert sum(item["id"] == "LETTER" for item in avatar.inventory) == 1
