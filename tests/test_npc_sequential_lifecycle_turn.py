"""Partial owner success survives publication, reload and a new independent decision."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.chpm.state import KEY, load
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.npc_actions import publication
from backend.engine.npc_actions.contracts import Give
from backend.engine.scene_illustrations.snapshots import REGISTRY_KEY, content_hash
from backend.models.chat import ChatMessage
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.npc_sequential_fixture import (
    COAT,
    FIRST_STORY,
    NEXT_STORY,
    SequentialRoles,
    interrupt_after_removal,
    observed_frames,
    owner_state,
    seed_sequential,
)
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import install
from tests.test_npc_additional_actions_turn import observe
from tests.test_npc_two_phase_turn import assert_committed, reload


def streamed_text(events):
    return "".join(
        json.loads(row.partition("\ndata: ")[2])["content"]
        for row in events
        if row.startswith("event: chunk")
    )


def assert_illustration(state, reply):
    snapshot = state.entity_states[REGISTRY_KEY]["snapshots"][reply.id]
    assert snapshot["narration"] == reply.content == FIRST_STORY
    assert snapshot["content_hash"] == content_hash(reply)
    people = {row["id"]: row for row in snapshot["visible_facts"]["characters"]}
    assert "MILA" not in people
    assert people["LINA"].get("managed_clothing") is True
    assert "Blue coat" not in json.dumps(people["LINA"].get("clothing_tokens", []))
    assert "PRIVATE_DESTINATION_MUST_NOT_LEAK" not in json.dumps(snapshot)


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_interrupted_transfer_preserves_removed_coat_and_next_observer_scoped_choice(
    monkeypatch, protocol
):
    roles = SequentialRoles()
    install(monkeypatch, roles)
    applied = interrupt_after_removal(monkeypatch)
    _, publications = observe(monkeypatch)
    async with TestSessionLocal() as db:
        user, state = await seed_sequential(db, protocol)
        session_id, user_id = state.session_id, user.id
        host, events = await run(db, user, "I quietly wait by the window.")
        assert_committed(events)
        assert streamed_text(events) == FIRST_STORY
        assert applied == ["take_off_item"]
        assert await owner_state(host) == ("LINA", set())
        first = deepcopy(publications[0].action_outcomes["LINA"])
        assert [row["status"] for row in first] == [
            "applied",
            "blocked",
        ]
        assert first[1]["reason_code"] == "unavailable_entity"
        assert not first[1].get("effect")
        previous = load(state).actors["LINA"]
        assert [row.status for row in previous.last_publication.operations] == [
            "applied",
            "blocked",
        ]
        reply_id = previous.reply_id
        reply = await db.get(ChatMessage, reply_id)
        assert_illustration(state, reply)
        assert previous.selected.intention.startswith("Remove my coat")

    async with TestSessionLocal() as db:
        user, host, snapshot = await reload(db, session_id, user_id)
        assert snapshot.owners[COAT] == "LINA"
        assert await owner_state(host) == ("LINA", set())
        assert host.state.entity_states["MILA"]["current_scene_id"] == "ANNEX"
        assert_illustration(host.state, await db.get(ChatMessage, reply_id))
        roles.steps = []
        host, events = await run(db, user, "The clock ticks. I say nothing.")
        assert_committed(events)
        assert streamed_text(events) == NEXT_STORY
        assert applied == ["take_off_item"]
        assert publications[-1].action_outcomes == {"LINA": []}
        body = roles.choices[-1][0]
        feedback = body["previous_action_results_not_current_state"]
        assert feedback["source_reply_id"] == reply_id
        assert [(row["operation_id"], row["status"]) for row in feedback["operations"]] == [
            (row["operation_id"], row["status"]) for row in first
        ]
        frames = observed_frames(body)
        assert frames[-1]["scene_id"] == "START"
        assert [row["id"] for row in frames[-1]["owned_items"]] == [COAT]
        assert frames[-1]["worn_item_ids"] == []
        assert "MILA" not in frames[-1]["visible_actor_ids"]
        assert all("PRIVATE_DESTINATION_MUST_NOT_LEAK" not in json.dumps(frame) for frame in frames)
        assert "PRIVATE_DESTINATION_MUST_NOT_LEAK" not in json.dumps(body)
        assert "ANNEX" not in json.dumps(body)
        assert await owner_state(host) == ("LINA", set())
        assert len(roles.executions) == 1


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_older_source_bound_ack_survives_regeneration_and_next_turn(monkeypatch, protocol):
    roles = SequentialRoles()
    install(monkeypatch, roles)
    interrupt_after_removal(monkeypatch)
    async with TestSessionLocal() as db:
        user, state = await seed_sequential(db, protocol)
        session_id, user_id = state.session_id, user.id
        _, events = await run(db, user, "I quietly wait by the window.")
        assert_committed(events)
        first = load(state).actors["LINA"]
        legacy_reply_id = first.reply_id
        legacy_operation_ids = {row.operation_id for row in first.last_publication.operations}
        saved = deepcopy(state.entity_states)
        saved[KEY]["actors"]["LINA"]["last_publication"].pop("execution")
        state.entity_states = saved
        await db.commit()

    async with TestSessionLocal() as db:
        user = await db.get(User, user_id)
        host = GameTurnManager(db, session_id, user)
        assert await host.initialize()
        legacy = load(host.state).actors["LINA"]
        assert legacy.last_publication.execution is None
        assert {
            row.operation_id for row in legacy.last_publication.operations
        } == legacy_operation_ids
        assert (await db.get(ChatMessage, legacy.reply_id)).content == FIRST_STORY
        assert await db.get(ChatMessage, legacy.observation.message_id) is not None
        assert await owner_state(host) == ("LINA", set())
        events = [
            row async for row in host.process_turn("ignored", replay_message_id=legacy_reply_id)
        ]
        assert_committed(events)
        current = load(host.state).actors["LINA"]
        assert current.reply_id != legacy_reply_id
        assert await db.get(ChatMessage, legacy_reply_id) is None
        assert await owner_state(host) == ("LINA", set())
        saved = deepcopy(host.state.entity_states)
        saved[KEY]["actors"]["LINA"]["last_publication"].pop("execution")
        host.state.entity_states = saved
        await db.commit()

    async with TestSessionLocal() as db:
        user, host, _ = await reload(db, session_id, user_id)
        prior = load(host.state).actors["LINA"]
        assert prior.last_publication.execution is None
        roles.steps = []
        _, events = await run(db, user, "The clock ticks. I say nothing.")
        assert_committed(events)
        body = roles.choices[-1][0]
        feedback = body["previous_action_results_not_current_state"]
        assert "execution" not in feedback
        assert feedback["source_reply_id"] == prior.reply_id
        assert [(row["operation_id"], row["status"]) for row in feedback["operations"]] == [
            (row.operation_id, row.status) for row in prior.last_publication.operations
        ]
        assert observed_frames(body)[-1]["worn_item_ids"] == []
        assert len(roles.executions) == 2


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("fault", ["lost_transfer", "failed_owner_write"])
async def test_broken_second_owner_write_rolls_back_successful_prefix_before_visible_output(
    monkeypatch, protocol, fault
):
    roles = SequentialRoles()
    install(monkeypatch, roles)
    original = publication._apply
    actual_states = []

    async def write(host, scope, request, preview):
        if isinstance(request, Give) and fault == "lost_transfer":
            return
        await original(host, scope, request, preview)
        actual_states.append(await owner_state(host))
        if isinstance(request, Give):
            raise RuntimeError("Simulated owner persistence failure after writing.")

    monkeypatch.setattr(publication, "_apply", write)
    async with TestSessionLocal() as db:
        user, state = await seed_sequential(db, protocol)
        session_id, user_id = state.session_id, user.id
        _, events = await run(db, user, "I quietly wait by the window.")
        assert actual_states[0] == ("LINA", set())
        if fault == "failed_owner_write":
            assert actual_states[1] == ("MILA", set())
        assert any(row.startswith("event: error") for row in events)
        assert not any(row.startswith(("event: chunk", "event: final")) for row in events)

    async with TestSessionLocal() as db:
        _, host, snapshot = await reload(db, session_id, user_id)
        assert snapshot.owners[COAT] == "LINA"
        assert await owner_state(host) == ("LINA", {COAT})
        assert not load(host.state).actors
        assert not host.state.entity_states.get(REGISTRY_KEY, {}).get("snapshots")
        assert not await db.scalar(select(ChatMessage).where(ChatMessage.content == FIRST_STORY))


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_full_regeneration_restores_prechoice_owners_and_replaces_history_once(
    monkeypatch, protocol
):
    roles = SequentialRoles()
    install(monkeypatch, roles)
    applied = interrupt_after_removal(monkeypatch)
    _, publications = observe(monkeypatch)
    async with TestSessionLocal() as db:
        user, state = await seed_sequential(db, protocol)
        session_id, user_id = state.session_id, user.id
        host, events = await run(db, user, "I quietly wait by the window.")
        assert_committed(events)
        original = load(state).actors["LINA"]
        old_reply_id = original.reply_id
        old_ops = deepcopy(publications[0].action_outcomes["LINA"])
        assert await owner_state(host) == ("LINA", set())

    async with TestSessionLocal() as db:
        user = await db.get(User, user_id)
        host = GameTurnManager(db, session_id, user)
        events = [row async for row in host.process_turn("ignored", replay_message_id=old_reply_id)]
        assert_committed(events)
        assert any(row.startswith("event: replay_history") for row in events)
        assert applied == ["take_off_item", "take_off_item"]
        assert await owner_state(host) == ("LINA", set())
        current = load(host.state).actors["LINA"]
        assert current.reply_id != old_reply_id
        assert await db.get(ChatMessage, old_reply_id) is None
        assert old_reply_id not in host.state.entity_states[REGISTRY_KEY]["snapshots"]
        assert_illustration(host.state, await db.get(ChatMessage, current.reply_id))
        new_ops = publications[-1].action_outcomes["LINA"]
        assert [row["status"] for row in new_ops] == [row["status"] for row in old_ops]
        assert {row["attempt_id"] for row in old_ops}.isdisjoint(
            row["attempt_id"] for row in new_ops
        )
        assert not roles.choices[-1][0].get("previous_action_results_not_current_state")
        history = list(
            await db.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.content == FIRST_STORY,
                )
            )
        )
        assert len(history) == 1
