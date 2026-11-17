"""Planning is ordered, observer-bound and isolated from every canonical state owner."""

from copy import deepcopy

from backend.engine import turn_controls
from backend.engine.chpm.observable_state import project
from backend.engine.clothing.context import actor_records
from backend.engine.npc_actions.contracts import ChangeState, Discard, Give, Move, PutDown, Take
from backend.engine.npc_actions.preview import Draft, Scope
from backend.engine.physical_conditions.ledger import read
from backend.engine.visual_novel.continuity import possession_snapshot
from tests.npc_control_support import bind_observation
from tests.observable_state_support import observation, world


def fixture():
    host, rows = world()
    observed = observation()
    bind_observation(host, observed)
    view = project(host, rows, "npc", observed)
    scope = Scope(
        host.game_id,
        view.message_id,
        "npc",
        view.scene_id,
        actor_records(host, rows),
        possession_snapshot(host, rows),
        host.state.entity_states,
        frozenset(view.entities),
        frozenset({"PORCH"}),
        input_revision=observed.revision_id,
        input_hash=observed.content_hash,
        observation=observed,
        control=turn_controls.scope(host, "npc_command_preview", observation=observed),
    )
    return host, scope, Draft(scope)


def test_chained_take_property_and_give_preserve_all_owners_until_publication():
    host, scope, draft = fixture()
    before = deepcopy(scope), deepcopy(host.state.entity_states)
    assert draft.execute(Take(tool="take_item", item_id="KEY"))["status"] == "staged"
    assert (
        draft.execute(
            ChangeState(
                tool="change_item_state",
                item_id="KEY",
                dimension="surface",
                detail="Scratched handle.",
            )
        )["status"]
        == "staged"
    )
    assert (
        draft.execute(Give(tool="give_item", item_id="KEY", recipient_id="other"))["status"]
        == "staged"
    )
    assert scope == before[0] and host.state.entity_states == before[1]
    assert len(draft.requests) == 3
    assert draft._possessions.owners["KEY"] == "other"
    assert any(row.detail == "Scratched handle." for row in read(draft._states).conditions.values())


def test_failed_acquisition_cannot_authorize_a_later_property_change_or_transfer():
    _, _, draft = fixture()
    assert draft.execute(Take(tool="take_item", item_id="OTHER_COAT"))["status"] == "blocked"
    assert (
        draft.execute(
            ChangeState(
                tool="change_item_state", item_id="OTHER_COAT", dimension="surface", detail="Torn."
            )
        )["status"]
        == "blocked"
    )
    assert draft.requests == []


def test_hidden_ids_and_room_travel_cannot_grant_new_scene_access():
    _, _, draft = fixture()
    assert draft.execute(Take(tool="take_item", item_id="HIDDEN"))["status"] == "unavailable_entity"
    assert draft.execute(Move(tool="move_to", destination_scene_id="PORCH"))["status"] == "staged"
    assert draft.execute(Take(tool="take_item", item_id="KEY"))["status"] == "scene_frame_ended"
    assert draft.execute(Discard(tool="discard_actions"))["status"] == "discarded"
    assert draft.requests == []
    assert draft.execute(Take(tool="take_item", item_id="KEY"))["status"] == "staged"


def test_discard_rebuilds_the_preview_without_leaking_earlier_effects():
    _, _, draft = fixture()
    assert (
        draft.execute(PutDown(tool="put_down_item", item_id="FLASK", position="on a shelf"))[
            "status"
        ]
        == "staged"
    )
    assert draft.execute(Discard(tool="discard_actions"))["status"] == "discarded"
    assert (
        draft.execute(PutDown(tool="put_down_item", item_id="FLASK", position="on a bench"))[
            "status"
        ]
        == "staged"
    )
    assert draft._possessions.items["FLASK"]["spatial_position"] == "on a bench"


def test_departure_reduces_the_offered_action_surface_to_abandoning_the_plan():
    _, _, draft = fixture()
    assert {"take_item", "move_to"} <= draft.available_tools()
    assert draft.execute(Move(tool="move_to", destination_scene_id="PORCH"))["status"] == "staged"
    assert draft.available_tools() == {"discard_actions"}


def test_acquisition_can_be_followed_by_transfer_in_the_same_two_call_batch():
    _, _, draft = fixture()
    offered = draft.available_tools()
    assert {"take_item", "give_item"} <= offered
    assert draft.execute(Take(tool="take_item", item_id="KEY"))["status"] == "staged"
    assert (
        draft.execute(Give(tool="give_item", item_id="KEY", recipient_id="other"))["status"]
        == "staged"
    )
