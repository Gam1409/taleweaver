"""Final publication feedback remains source-bound and private to the deciding actor."""

from hashlib import sha256

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.sessions import copy_session
from backend.engine import turn_controls
from backend.engine.chpm import lifecycle
from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.chpm.runtime import Turn
from backend.engine.chpm.schema import KernelState, Observation, Settings
from backend.engine.chpm.state import KEY as CHPM_KEY
from backend.engine.chpm.state import load, retract
from backend.engine.clothing.visuals import session_objects
from backend.engine.npc_actions.contracts import Give, Take
from backend.engine.npc_actions.preparation import capture as capture_actions
from backend.engine.npc_actions.publication import publish
from backend.engine.turn_replay.snapshot import capture as snapshot
from backend.engine.turn_replay.snapshot import restore
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.npc_control_support import bind_observation
from tests.test_chpm_kernel import decision
from tests.test_npc_action_publication import fixture


async def competing_publication(db, *, empty=False):
    manager, observed, drafts = await fixture(db)
    source = await db.get(ChatMessage, observed.message_id)
    observed = observed.model_copy(update={"source_scene_id": source.scene_id})
    bind_observation(manager, observed)
    first, second = drafts["LINA"], drafts["SECOND"]
    assert first.execute(Take(tool="take_item", item_id="KEY"))["status"] == "staged"
    if not empty:
        assert second.execute(Take(tool="take_item", item_id="KEY"))["status"] == "staged"
        assert (
            second.execute(Give(tool="give_item", item_id="KEY", recipient_id="@player"))["status"]
            == "staged"
        )
    first.approved = second.approved = True
    outcomes = {"LINA": await publish(manager, first), "SECOND": await publish(manager, second)}
    assert [record["status"] for record in outcomes["SECOND"]] == (
        [] if empty else ["blocked", "skipped_dependency"]
    )
    return await completed_turn(db, manager, observed, drafts, outcomes)


async def completed_turn(db, manager, observed, drafts, outcomes):
    reply = ChatMessage(
        session_id=manager.game_id,
        role="assistant",
        content="The visitors finish their turn.",
        scene_id="START",
    )
    db.add(reply)
    await db.commit()
    decisions = {
        actor: decision().model_copy(
            update={
                "actor_id": actor,
                "observation": observed,
                "status": "delivered",
                "reply_id": reply.id,
                "reply_revision": reply.revision_id,
                "reply_hash": sha256(reply.content.encode()).hexdigest(),
            }
        )
        for actor in drafts
    }
    initial = KernelState(
        settings=Settings(
            mode="live",
            workflow="integrated",
            action_tools=True,
            actor_ids=list(drafts),
            agent_steps=2,
        )
    )
    current = Turn(
        initial,
        observed.message_id,
        decisions=decisions,
        action_drafts=drafts,
        action_outcomes=outcomes,
        control=turn_controls.scope(manager, "narration_review", observation=observed),
    )
    return manager, observed, reply, current


async def cached(db, *, empty=False):
    from backend.engine.npc_actions import acknowledgment

    manager, observed, reply, current = await competing_publication(db, empty=empty)
    previous = current.decisions["SECOND"]
    previous.last_publication = acknowledgment.capture(current, previous)
    manager.state.entity_states = {
        **manager.state.entity_states,
        CHPM_KEY: KernelState(
            settings=current.initial.settings, actors={"SECOND": previous}
        ).model_dump(mode="json"),
    }
    await db.commit()
    return manager, observed, reply, current, load(manager.state).actors["SECOND"]


async def next_input(manager, db):
    message = ChatMessage(
        session_id=manager.game_id, role="user", content="What will you do next?", scene_id="START"
    )
    db.add(message)
    await db.commit()
    manager._vn_player_message_id = message.id
    turn_controls.begin(manager)
    observed = Observation(
        session_id=manager.game_id,
        message_id=message.id,
        revision_id=message.revision_id,
        content_hash=sha256(message.content.encode()).hexdigest(),
        sequence=1,
        scene_id="START",
        minute=0,
        player_request=message.content,
    )
    bind_observation(manager, observed)
    return observed


async def test_real_conflict_final_results_reach_only_the_same_npc_on_the_next_decision():
    async with TestSessionLocal() as db:
        manager, observed, reply, current = await competing_publication(db)
        from backend.engine.npc_actions import acknowledgment

        previous = current.decisions["SECOND"]
        previous.last_publication = acknowledgment.capture(current, previous)
        assert [operation.status for operation in previous.last_publication.operations] == [
            "blocked",
            "skipped_dependency",
        ]
        restored = type(previous).model_validate_json(previous.model_dump_json())
        upcoming = await next_input(manager, db)
        supplied = await acknowledgment.context(manager, restored, upcoming, "SECOND")
        assert supplied["meaning"] == "historical_publication_acknowledgment_not_current_state"
        assert supplied["source_input_id"] == observed.message_id
        assert supplied["source_reply_id"] == reply.id
        assert [operation["status"] for operation in supplied["operations"]] == [
            "blocked",
            "skipped_dependency",
        ]
        assert all(
            set(operation)
            <= {
                "operation_id",
                "tool",
                "status",
                "reason_code",
                "item_id",
                "target_id",
                "recipient_id",
                "destination_scene_id",
            }
            for operation in supplied["operations"]
        )
        assert [operation["item_id"] for operation in supplied["operations"]] == ["KEY", "KEY"]
        assert supplied["operations"][1]["recipient_id"] == "@player"
        first_operation = current.action_outcomes["LINA"][0]["operation_id"]
        assert first_operation not in str(supplied)
        assert "effect" not in str(supplied)
        assert previous.spoken_evidence == previous.action_evidence == ""


async def test_reordered_same_tool_results_keep_each_trusted_item_operand_with_its_operation():
    from backend.engine.npc_actions import acknowledgment

    async with TestSessionLocal() as db:
        manager, observed, _ = await fixture(db)
        observed = observed.model_copy(update={"source_scene_id": "START"})
        bind_observation(manager, observed)
        db.add(
            WorldEntity(
                id="SECOND_KEY",
                session_id=manager.game_id,
                entity_type="OBJECT",
                name="Another key",
                description="A second portable key.",
                current_scene_id="START",
            )
        )
        await db.commit()
        drafts = await capture_actions(
            manager, await capture_views(manager, ["LINA", "SECOND"], observed), observed
        )
        for item_id in ("KEY", "SECOND_KEY"):
            assert (
                drafts["LINA"].execute(Take(tool="take_item", item_id=item_id))["status"]
                == "staged"
            )
        assert (
            drafts["SECOND"].execute(Take(tool="take_item", item_id="SECOND_KEY"))["status"]
            == "staged"
        )
        drafts["LINA"].approved = drafts["SECOND"].approved = True
        outcomes = {
            "SECOND": await publish(manager, drafts["SECOND"]),
            "LINA": await publish(manager, drafts["LINA"]),
        }
        assert [row["status"] for row in outcomes["LINA"]] == ["applied", "blocked"]
        _, _, _, current = await completed_turn(db, manager, observed, drafts, outcomes)
        current.action_outcomes["LINA"].reverse()
        drafts["LINA"].published_results.reverse()

        result = acknowledgment.capture(current, current.decisions["LINA"])

        by_id = {row.operation_id: (row.item_id, row.status) for row in result.operations}
        first, second = drafts["LINA"].operations
        assert by_id == {
            first.operation_id: ("KEY", "applied"),
            second.operation_id: ("SECOND_KEY", "blocked"),
        }
        assert drafts["SECOND"].operations[0].operation_id not in by_id


async def test_empty_approved_publication_is_distinct_from_no_acknowledgment():
    from backend.engine.npc_actions import acknowledgment

    async with TestSessionLocal() as db:
        manager, _, _, _, previous = await cached(db, empty=True)
        assert previous.last_publication is not None
        assert previous.last_publication.operations == ()
        supplied = await acknowledgment.context(
            manager, previous, await next_input(manager, db), "SECOND"
        )
        assert supplied is not None and supplied["operations"] == []


async def test_applied_acknowledgment_remains_historical_after_a_later_valid_owner_transfer():
    from backend.engine.npc_actions import acknowledgment

    async with TestSessionLocal() as db:
        manager, _, _, current = await competing_publication(db)
        previous = current.decisions["LINA"]
        previous.last_publication = acknowledgment.capture(current, previous)
        previous = type(previous).model_validate_json(previous.model_dump_json())
        upcoming = await next_input(manager, db)
        views = await capture_views(manager, ["LINA"], upcoming)
        draft = (await capture_actions(manager, views, upcoming))["LINA"]
        assert (
            draft.execute(Give(tool="give_item", item_id="KEY", recipient_id="SECOND"))["status"]
            == "staged"
        )
        draft.approved = True
        assert (await publish(manager, draft))[0]["status"] == "applied"
        owners = possession_snapshot(manager, await session_objects(db, manager.game_id)).owners
        assert owners["KEY"] == "SECOND"

        supplied = await acknowledgment.context(manager, previous, upcoming, "LINA")

        assert supplied is not None and supplied["operations"][0]["status"] == "applied"
        assert supplied["meaning"] == "historical_publication_acknowledgment_not_current_state"
        assert supplied["operations"][0]["item_id"] == "KEY" and "effect" not in str(supplied)


@pytest.mark.parametrize("source", ["input", "reply"])
@pytest.mark.parametrize(
    "change", ["role", "revision", "hash", "scene", "debug", "incomplete", "missing"]
)
async def test_previous_source_rows_are_revalidated_before_feedback_is_supplied(source, change):
    from backend.engine.npc_actions import acknowledgment

    async with TestSessionLocal() as db:
        manager, observed, reply, _, previous = await cached(db)
        upcoming = await next_input(manager, db)
        row = await db.get(ChatMessage, observed.message_id) if source == "input" else reply
        if change == "role":
            row.role = "system"
        if change == "revision":
            row.revision_id = "another-revision"
        if change == "hash":
            row.content += " An edited source."
        if change == "scene":
            row.scene_id = "another-scene"
        if change == "debug":
            row.is_debug = True
        if change == "incomplete":
            row.npc_journal = {"status": "incomplete"}
        if change == "missing":
            await db.delete(row)
        await db.commit()

        assert await acknowledgment.context(manager, previous, upcoming, "SECOND") is None


@pytest.mark.parametrize(
    "actor,updates",
    [
        ("LINA", {}),
        ("unavailable", {}),
        ("SECOND", {"source_scene_id": None}),
        ("SECOND", {"session_id": "foreign"}),
    ],
)
async def test_cached_feedback_never_borrows_foreign_actor_or_input_source(actor, updates):
    from backend.engine.npc_actions import acknowledgment

    async with TestSessionLocal() as db:
        manager, _, _, _, previous = await cached(db)
        previous.observation = previous.observation.model_copy(update=updates)
        upcoming = await next_input(manager, db)
        assert await acknowledgment.context(manager, previous, upcoming, actor) is None


async def test_current_or_undelivered_decisions_do_not_become_historical_feedback():
    from backend.engine.npc_actions import acknowledgment

    async with TestSessionLocal() as db:
        manager, observed, _, _, previous = await cached(db)
        assert await acknowledgment.context(manager, previous, observed, "SECOND") is None
        upcoming = await next_input(manager, db)
        previous.status = "selected"
        assert await acknowledgment.context(manager, previous, upcoming, "SECOND") is None


@pytest.mark.parametrize("mode", ["off", "shadow"])
async def test_opt_out_and_shadow_do_not_capture_publication_feedback(mode):
    from backend.engine.npc_actions import acknowledgment

    async with TestSessionLocal() as db:
        _, _, _, current = await competing_publication(db)
        current.initial.settings.mode = mode
        assert acknowledgment.capture(current, current.decisions["SECOND"]) is None


@pytest.mark.parametrize("source", ["input", "reply"])
async def test_retracting_either_source_drops_the_cached_acknowledgment(source):
    async with TestSessionLocal() as db:
        manager, observed, reply, _, previous = await cached(db)
        assert previous.last_publication is not None
        retract(manager.state, observed.message_id if source == "input" else reply.id)
        assert load(manager.state).actors == {}


async def test_session_fork_discards_source_session_publication_feedback():
    async with TestSessionLocal() as db:
        manager, observed, reply, _, previous = await cached(db)
        assert previous.last_publication is not None
        changed = lifecycle.fork(
            manager.state.entity_states,
            {observed.message_id: "fork-input", reply.id: "fork-reply"},
            "fork-session",
        )
        assert KernelState.model_validate(changed[CHPM_KEY]).actors == {}
        assert load(manager.state).actors["SECOND"].last_publication == previous.last_publication


async def test_real_session_copy_does_not_reuse_cached_publication_feedback():
    async with TestSessionLocal() as db:
        manager, _, _, _, previous = await cached(db)
        user = await db.get(User, manager.state.user_id)
        copied = await copy_session(manager.game_id, db, user)
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == copied["game_id"])
        )
        assert load(state).actors == {}
        assert load(manager.state).actors["SECOND"].last_publication == previous.last_publication


async def test_snapshot_restore_restores_the_source_bound_last_acknowledgment():
    from backend.engine.npc_actions import acknowledgment

    async with TestSessionLocal() as db:
        manager, _, _, _, previous = await cached(db)
        saved = await snapshot(db, manager.game_id)
        state = load(manager.state)
        state.actors = {}
        manager.state.entity_states = {
            **manager.state.entity_states,
            CHPM_KEY: state.model_dump(mode="json"),
        }
        await db.commit()
        await restore(db, manager.game_id, saved)
        await db.commit()
        await db.refresh(manager.state)
        await db.refresh(manager.avatar)
        restored = load(manager.state).actors["SECOND"]
        assert restored.last_publication == previous.last_publication
        supplied = await acknowledgment.context(
            manager, restored, await next_input(manager, db), "SECOND"
        )
        assert [operation["status"] for operation in supplied["operations"]] == [
            "blocked",
            "skipped_dependency",
        ]
