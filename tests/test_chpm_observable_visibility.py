"""Public surfaces, ownership changes and tool budgets do not widen NPC knowledge."""

from copy import deepcopy

import pytest

from backend.engine.chpm.agent_limits import MAX_PINNED_CHARS
from backend.engine.scene_staging import props
from tests.observable_state_support import garment, profile, proposal, save, tools_for, world
from tests.test_chpm_host_state import source
from tests.test_chpm_observable_state import body, inspect


def test_public_surface_does_not_expose_nonvisual_item_details():
    manager, rows = world()
    public = "The bell has a visible crack."
    private = " Its hidden interior bears PRIVATE_INTERIOR."
    save(manager, [proposal("BELL", public + private, visual_detail=public)])
    view = body(tools_for(manager, rows), "BELL")
    assert view["recorded_conditions"][0]["detail"] == public
    assert "PRIVATE_INTERIOR" not in str(view)


@pytest.mark.parametrize("public", [False, True])
def test_player_placement_requires_public_evidence_and_uses_existing_player_alias(public):
    manager, rows = world()
    manager.state.entity_states[props.KEY] = {
        "items": [
            {
                "item_id": "PLAYER_BAG_SECRET",
                "owner_id": manager.avatar.id,
                "scene_id": "room",
                "status": "confirmed",
                "spatial_position": "on the bench",
                "visibility": "public" if public else "private",
            }
        ]
    }
    tools = tools_for(manager, rows)
    if not public:
        assert inspect(tools, "PLAYER_BAG_SECRET") == {"status": "unavailable_entity"}
        return
    assert body(tools, "PLAYER_BAG_SECRET")["owner_id"] == "@player"


def test_transfer_changes_access_without_replacing_the_existing_item_fact():
    manager, rows = world()
    condition_id = save(manager, [proposal(visibility="private")])[0]
    assert body(tools_for(manager, rows), "FLASK")["owner_id"] == "npc"
    manager.state.entity_states.update(
        {
            "npc": {"inventory": ["COAT", "LINING"]},
            "other": {"inventory": ["OTHER_COAT", "OTHER_INNER", "FLASK"]},
        }
    )
    assert inspect(tools_for(manager, rows), "FLASK") == {"status": "unavailable_entity"}
    view = body(tools_for(manager, rows, "other"), "FLASK")
    assert view["owner_id"] == "other"
    assert view["recorded_conditions"][0]["id"] == condition_id


def test_current_scene_override_removes_old_room_access():
    manager, rows = world()
    assert body(tools_for(manager, rows), "KEY")["id"] == "KEY"
    manager.state.entity_states["KEY"] = {"current_scene_id": "elsewhere"}
    assert inspect(tools_for(manager, rows), "KEY") == {"status": "unavailable_entity"}


def test_exhausted_source_budget_does_not_record_a_new_observation():
    manager, rows = world()
    tools = tools_for(manager, rows)
    for index in range(3):
        full = source(text="x" * (MAX_PINNED_CHARS // 3))
        assert tools.expose(f"known-{index}", full, full=True)["status"] == "ok"
    before = tools.mind.model_dump_json()
    assert inspect(tools, "COAT")["status"] == "evidence_budget_exhausted"
    assert tools.mind.model_dump_json() == before


def test_static_description_cannot_replace_current_item_state():
    manager, rows = world()
    next(row for row in rows if row.id == "KEY").description = "OBSOLETE_DESCRIPTION"
    save(manager, [proposal("KEY", "The key has been straightened.", part="form")])
    view = body(tools_for(manager, rows), "KEY")
    assert "straightened" in str(view) and "OBSOLETE_DESCRIPTION" not in str(view)


def test_valid_existing_conditions_do_not_require_a_nonzero_revision():
    from backend.engine.physical_conditions.ledger import read
    from backend.engine.physical_conditions.schema import KEY

    manager, rows = world()
    save(manager, [proposal()])
    manager.state.entity_states[KEY]["revision"] = 0
    assert read(manager.state.entity_states).conditions
    view = body(tools_for(manager, rows), "FLASK")
    assert view["recorded_conditions"][0]["detail"] == "The flask is half full."


def test_equipment_only_clothing_uses_the_existing_wear_projection():
    manager, rows = world()
    armor = garment("ARMOR", layer=3)
    rows.append(armor)
    manager.avatar.visual_profile = profile()
    manager.avatar.equipment = {
        "Chest": {"id": "ARMOR", "name": "ARMOR", "clothing": armor.metadata_json["clothing"]}
    }
    view = body(tools_for(manager, rows), "ARMOR")
    assert view["worn_by"] == "@player" and view["wear_status"] == "worn"


def test_two_observers_reading_one_item_cannot_duplicate_its_ownership():
    from backend.engine.clothing.context import actor_records
    from backend.engine.narrated_items.apply import apply_actions
    from backend.engine.narrated_items.schema import ItemAction, ItemExtraction
    from backend.engine.visual_novel.continuity import possession_snapshot

    manager, rows = world()
    assert body(tools_for(manager, rows), "KEY")["owner_id"] == "__scene__"
    assert body(tools_for(manager, rows, "other"), "KEY")["owner_id"] == "__scene__"
    actors = actor_records(manager, rows)
    before = deepcopy(actors)
    statements = ["The first observer picks up the key.", "The second observer picks up the key."]
    actions = [
        ItemAction(
            item_id="KEY",
            source_owner="__scene__",
            destination_owner=actor,
            disposition="carried",
            basis="completed",
            evidence=quote,
        )
        for actor, quote in zip(("npc", "other"), statements, strict=True)
    ]
    changed, accepted, errors = apply_actions(
        ItemExtraction(actions=actions),
        actors,
        possession_snapshot(manager, rows),
        " ".join(statements),
        detailed=False,
        session_id="session",
        message_id="reply",
    )
    holders = [
        actor
        for actor in changed.values()
        if any(
            (item.get("id") if isinstance(item, dict) else item) == "KEY"
            for item in actor["inventory"]
        )
    ]
    assert len(holders) <= 1 and len(accepted) <= 1 and errors
    assert actors == before
