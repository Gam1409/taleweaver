"""Narrated movements cannot bypass canonical routes, evidence or individual actor limits."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.narrated_movement.context import context
from backend.engine.narrated_movement.runtime import Pending, _event
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn

TEXT = "Rin left the room. Miki entered the laboratory. I followed Miki."
PLAYER = "I enter the laboratory."


def pending(proposals):
    actor = {"can_move": True, "presence": "present", "allowed_destinations": ["LAB"]}
    return Pending(
        before={
            "scene_id": "ROOM",
            "actors": {key: deepcopy(actor) for key in ("RIN", "MIKI", "__player__")},
        },
        narration=TEXT,
        player_message=PLAYER,
        proposals=proposals,
    )


def move(**changes):
    return {
        "actor_id": "RIN",
        "destination_scene_id": "LAB",
        "presence": "present",
        "basis": "completed",
        "evidence": "Rin left the room.",
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_id": "FOREIGN"},
        {"destination_scene_id": "NONADJACENT"},
        {"evidence": "An invented departure."},
        {"basis": "intention"},
        {"basis": "historical"},
        {"basis": "attempt"},
        {"basis": "uncertain"},
        {"actor_id": "__player__", "player_evidence": "I never said this."},
        {"actor_id": "__player__", "player_evidence": None},
    ],
)
def test_unconfirmed_or_unavailable_travel_does_not_mutate_world_events(changes):
    event, accepted, errors = _event(pending([move(**changes)]))
    assert errors and not accepted
    assert not event.new_scene_id and not event.moved_entities and not event.updated_entities


@pytest.mark.parametrize("reason", ["stationary", "blocked", "locked"])
def test_one_rejected_actor_does_not_cancel_an_independent_allowed_departure(reason):
    batch = pending([move(), move(actor_id="MIKI", evidence="Miki entered the laboratory.")])
    if reason == "stationary":
        batch.before["actors"]["RIN"]["can_move"] = False
    elif reason == "locked":
        batch.before["actors"]["RIN"]["allowed_destinations"] = []
    else:
        batch.denied = frozenset({"RIN"})
    event, accepted, errors = _event(batch)
    assert len(accepted) == len(errors) == 1
    assert [row.entity_id for row in event.moved_entities] == ["MIKI"]


def test_conflicting_final_destinations_are_not_resolved_by_arbitrary_list_order():
    event, accepted, errors = _event(
        pending([move(), move(destination_scene_id=None, presence="absent")])
    )
    assert len(errors) == 2 and not accepted and not event.moved_entities


def test_same_location_confirmation_does_not_clear_an_existing_position():
    event, accepted, errors = _event(pending([move(destination_scene_id="ROOM")]))
    assert accepted and not errors and not event.moved_entities
    assert event.updated_entities[0].presence == "present"


def test_player_authorization_and_local_presence_are_separate_from_npc_map_travel():
    event, accepted, errors = _event(
        pending(
            [
                move(actor_id="__player__", player_evidence=PLAYER, evidence="I followed Miki."),
                move(destination_scene_id=None, presence="audible"),
            ]
        )
    )
    assert len(accepted) == 2 and not errors
    assert event.new_scene_id == "LAB" and not event.moved_entities
    assert event.updated_entities[0].presence == "audible"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exit_type,locked,reverse,allowed,can_move,expected",
    [
        ("one_way", False, False, [], True, True),
        ("one_way", False, True, [], True, False),
        ("bidirectional", False, True, [], True, True),
        ("bidirectional", True, False, [], True, False),
        ("bidirectional", False, False, ["START"], True, False),
        ("bidirectional", False, False, ["lab"], True, True),
        ("bidirectional", False, False, [], False, False),
    ],
)
async def test_route_context_uses_session_locks_directions_and_effective_npc_permissions(
    exit_type, locked, reverse, allowed, can_move, expected
):
    from types import SimpleNamespace

    async with TestSessionLocal() as db:
        _, _, state, _ = await seed_vn(db)
        db.add(
            WorldScene(
                id="LAB",
                session_id=state.session_id,
                label="Laboratory",
                description="Bright room.",
            )
        )
        db.add(
            WorldExit(
                session_id=state.session_id,
                from_scene_id="LAB" if reverse else "START",
                to_scene_id="START" if reverse else "LAB",
                label="Door",
                exit_type=exit_type,
                is_locked=locked,
            )
        )
        state.entity_states = {
            **state.entity_states,
            "LINA": {"moveable": can_move, "allowed_scenes": allowed},
        }
        await db.flush()
        rows = list(
            await db.scalars(select(WorldEntity).where(WorldEntity.session_id == state.session_id))
        )
        result = await context(SimpleNamespace(db=db, state=state), rows)
        assert ("LAB" in result["actors"]["LINA"]["allowed_destinations"]) is expected
        assert "ABSENT" not in result["actors"]
        assert "SECRET_GOAL_NOT_PUBLIC" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["text", "permissions"])
async def test_pending_movement_cannot_commit_after_its_source_or_permissions_change(change):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from backend.engine.narrated_movement.runtime import complete, finish, prepare

    async with TestSessionLocal() as db:
        _, _, state, _ = await seed_vn(db)
        state.entity_states = {**state.entity_states, "LINA": {"moveable": True}}
        rows = list(
            await db.scalars(select(WorldEntity).where(WorldEntity.session_id == state.session_id))
        )
        manager = SimpleNamespace(db=db, state=state, _save_chat_message=AsyncMock())
        text = "Lina left the immediate scene, remaining within hearing."
        await prepare(manager, rows, text)
        complete(
            manager,
            [move(actor_id="LINA", destination_scene_id=None, presence="audible", evidence=text)],
        )
        if change == "permissions":
            state.entity_states = {**state.entity_states, "LINA": {"moveable": False}}
        before = deepcopy(state.entity_states)
        assert await finish(
            manager,
            SimpleNamespace(
                id="SAVED", content="Different final narration." if change == "text" else text
            ),
        )
        assert state.entity_states == before
        assert await finish(manager, SimpleNamespace(id="SAVED", content=text)) == []
