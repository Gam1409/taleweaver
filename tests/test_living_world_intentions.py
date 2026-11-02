"""Private intention lifecycle and source fencing, independent of model compliance."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.living_world import dialogue_memory as memory
from backend.engine.living_world.schema import Simulation
from backend.engine.living_world.state import fork, load, save
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from tests import test_living_world_decisions as decisions
from tests.conftest import TestSessionLocal

ready, world = decisions.ready, decisions.world


def choice(**updates):
    return memory.Choice(
        action="INITIATE",
        motive="Wants to help.",
        intention="Offer directions.",
        next_action="Offer to show the library.",
        reconsider_if="The player declines.",
        **updates,
    )


def manager_and_reply():
    state = SimpleNamespace(living_world=Simulation().model_dump(), current_scene_id="hall")
    manager = SimpleNamespace(state=state, _dialogue_intention=("npc", "hall", choice()))
    reply = SimpleNamespace(
        id="reply",
        revision_id="rev",
        content="Lina offered to show the library.",
        scene_id="hall",
    )
    return manager, reply


def test_intention_is_saved_only_after_completed_narration_and_not_as_world_fact():
    manager, reply = manager_and_reply()
    memory.remember_completed(manager, reply, completed=False)
    assert load(manager.state).dialogue_intentions == {}
    assert manager._dialogue_intention is None
    manager._dialogue_intention = ("npc", "hall", choice())
    memory.remember_completed(manager, reply, completed=True)
    simulation = load(manager.state)
    saved = simulation.dialogue_intentions["npc"]
    assert saved.source_message_id == "reply"
    assert saved.source_revision_id == "rev"
    assert saved.content_hash == memory.digest(reply.content)
    assert saved.choice.previous_outcome.status == "UNKNOWN"
    assert simulation.private_notes == {} and simulation.events == []
    revision = simulation.revision
    memory.remember_completed(manager, reply, completed=True)
    assert load(manager.state).revision == revision


def test_scene_change_does_not_attach_old_proposal_to_new_scene():
    manager, reply = manager_and_reply()
    reply.scene_id = "elsewhere"
    memory.remember_completed(manager, reply, completed=True)
    assert load(manager.state).dialogue_intentions == {}


@pytest.mark.parametrize(
    "status,quote,expected",
    [
        ("COMPLETED", "Lina opened the door.", "COMPLETED"),
        ("BLOCKED", "invented quotation", "UNKNOWN"),
        ("COMPLETED", "", "UNKNOWN"),
        ("UNKNOWN", "Lina opened the door.", "UNKNOWN"),
    ],
)
def test_outcome_requires_literal_evidence(status, quote, expected):
    proposal = choice(previous_outcome=memory.Outcome(status=status, quote=quote))
    grounded = memory.grounded_choice(
        proposal,
        {"result_narration_untrusted": "Lina opened the door."},
    )
    assert grounded.previous_outcome.status == expected
    assert memory.grounded_choice(proposal, {}).previous_outcome.status == "UNKNOWN"


def test_retraction_and_fork_preserve_only_valid_private_intentions():
    manager, reply = manager_and_reply()
    memory.remember_completed(manager, reply, completed=True)
    restored = Simulation.model_validate(fork(manager.state.living_world))
    assert restored.dialogue_intentions == load(manager.state).dialogue_intentions
    assert restored.timeline != load(manager.state).timeline
    memory.retract(manager.state, "another-message")
    assert "npc" in load(manager.state).dialogue_intentions
    memory.retract(manager.state, reply.id)
    assert load(manager.state).dialogue_intentions == {}


@pytest.mark.parametrize("change", ["none", "revision", "content", "missing", "session"])
async def test_previous_context_checks_actual_saved_source(ready, change):
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        message = ChatMessage(
            session_id=state.session_id,
            role="assistant",
            content="Lina offered directions.",
            scene_id=state.current_scene_id,
        )
        db.add(message)
        await db.flush()
        manager = SimpleNamespace(
            db=db,
            state=state,
            game_id=state.session_id,
            _dialogue_intention=("LILI", state.current_scene_id, choice()),
        )
        memory.remember_completed(manager, message, completed=True)
        await db.commit()
        simulation = load(state)
        if change == "revision":
            message.revision_id = "new-revision"
        if change == "content":
            message.content = "A different outcome."
        if change == "missing":
            await db.delete(message)
            await db.flush()
        if change == "session":
            manager.game_id = "another-session"
        result = await memory.previous_context(manager, simulation, "LILI")
        if change == "none":
            assert result["result_narration_untrusted"] == "Lina offered directions."
            assert result["proposal_not_fact"]["action"] == "INITIATE"
        else:
            assert result == {}
            assert simulation.dialogue_intentions == {}
        save(state, simulation)
