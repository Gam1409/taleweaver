"""Consumed feedback sources are validated as one cohort after model awaits."""

import pytest

from backend.engine import turn_controls
from backend.engine.chpm.errors import StaleControlError
from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.chpm.runtime import Turn
from backend.engine.chpm.schema import KernelState
from backend.engine.npc_actions import acknowledgment
from backend.engine.npc_actions.preparation import capture as capture_actions
from backend.engine.npc_actions.publication import publish
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_npc_publication_acknowledgment import cached, next_input


async def two_consumed_acknowledgments(db):
    manager, _, old_reply, first, second_previous = await cached(db)
    observed = await next_input(manager, db)
    observed = observed.model_copy(update={"source_scene_id": "START"})
    views = await capture_views(manager, ["LINA"], observed)
    draft = (await capture_actions(manager, views, observed))["LINA"]
    draft.approved = True
    outcomes = await publish(manager, draft)
    reply = ChatMessage(
        session_id=manager.game_id, role="assistant", content="Lina waits.", scene_id="START"
    )
    db.add(reply)
    await db.commit()
    lina = first.decisions["LINA"].model_copy(
        update={
            "observation": observed,
            "reply_id": reply.id,
            "reply_revision": reply.revision_id,
            "reply_hash": acknowledgment.digest(reply.content),
            "last_publication": None,
        }
    )
    previous_turn = Turn(
        first.initial,
        observed.message_id,
        decisions={"LINA": lina},
        action_drafts={"LINA": draft},
        action_outcomes={"LINA": outcomes},
        control=turn_controls.scope(manager, "narration_review", observation=observed),
    )
    lina.last_publication = acknowledgment.capture(previous_turn, lina)
    upcoming = await next_input(manager, db)
    priors = {"SECOND": second_previous, "LINA": lina}
    supplied = {
        actor: await acknowledgment.context(manager, previous, upcoming, actor)
        for actor, previous in priors.items()
    }
    assert all(supplied.values())
    current = Turn(
        KernelState(actors=priors),
        upcoming.message_id,
        decisions={
            actor: previous.model_copy(update={"observation": upcoming})
            for actor, previous in priors.items()
        },
        publication_feedback=supplied,
    )
    return manager, old_reply, reply, current


async def test_later_actor_anchor_read_cannot_leave_an_earlier_silent_source_unchecked(monkeypatch):
    async with TestSessionLocal() as db:
        manager, earlier_reply, later_reply, current = await two_consumed_acknowledgments(db)
        original = db.scalars

        async def edit_earlier_source(statement, *args, **kwargs):
            source_ids = next(
                value for value in statement.compile().params.values() if isinstance(value, list)
            )
            if later_reply.id in source_ids:
                earlier_reply.content = (
                    "The earlier silent source changed while reading the later source."
                )
            return await original(statement, *args, **kwargs)

        monkeypatch.setattr(db, "scalars", edit_earlier_source)
        with pytest.raises(StaleControlError, match="acknowledgment source changed"):
            await acknowledgment.ensure_current(manager, current)


async def test_all_consumed_actors_share_one_bounded_source_snapshot(monkeypatch):
    async with TestSessionLocal() as db:
        manager, _, _, current = await two_consumed_acknowledgments(db)
        original = db.scalars
        reads = []

        async def record(statement, *args, **kwargs):
            reads.append(statement)
            return await original(statement, *args, **kwargs)

        monkeypatch.setattr(db, "scalars", record)
        await acknowledgment.ensure_current(manager, current)
        assert len(reads) == 1
        anchors = next(
            value for value in reads[0].compile().params.values() if isinstance(value, list)
        )
        assert len(anchors) == 4
