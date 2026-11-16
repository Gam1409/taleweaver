"""Observable reads preserve identity, source scope, current properties and privacy."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from backend.engine.chpm import agent_context, agent_observable, observable_state, tool_feedback
from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.native_tool_contracts import parse_call, tool_definitions
from backend.engine.physical_conditions.ledger import read
from backend.engine.physical_conditions.schema import KEY
from backend.engine.scene_staging import props
from tests.observable_state_support import entity, proposal, save, tools_for, world
from tests.test_chpm_kernel import observation


def test_observable_state_inspection_is_offered_without_a_notebook():
    names = {row["function"]["name"] for row in tool_definitions(False)}
    assert "inspect_entity" in names
    request = parse_call("inspect_entity", '{"argument":"FLASK"}')
    assert isinstance(request, Lookup) and request.argument == "FLASK"


def inspect(tools, identifier):
    return tools.execute(Lookup(tool="inspect_entity", argument=identifier))


def body(tools, identifier):
    result = inspect(tools, identifier)
    assert result["status"] == "ok", result
    return json.loads(result["text"])


def test_own_current_item_properties_are_citable_without_mutating_world():
    manager, rows = world()
    identifier = save(manager, [proposal()])[0]
    before = deepcopy(vars(manager.state))
    tools = tools_for(manager, rows)
    result = inspect(tools, "FLASK")
    view = json.loads(result["text"])
    assert view["owner_id"] == "npc" and view["wear_status"] == "not_worn"
    assert view["recorded_conditions"] == [
        {
            "id": identifier,
            "kind": "item_state",
            "part": "contents",
            "status": "active",
            "detail": "The flask is half full.",
        }
    ]
    assert vars(manager.state) == before
    assert result["source_id"] in tools.pins
    assert agent_context.collect(tools.pins, tools.observation)[0].text == result["text"]
    assert Mind.model_validate_json(tools.mind.model_dump_json()) == tools.mind


def test_existing_item_identity_has_latest_property_only():
    manager, rows = world()
    identifier = save(manager, [proposal()])[0]
    save(
        manager,
        [
            {
                "operation": "change",
                "condition_id": identifier,
                "detail": "The flask is empty.",
                "evidence": "The flask is empty.",
                "visual_detail": "The flask is empty.",
                "visual_region": "torso",
            }
        ],
        "emptied",
    )
    view = body(tools_for(manager, rows), "FLASK")
    assert view["recorded_conditions"][0]["id"] == identifier
    assert view["recorded_conditions"][0]["detail"] == "The flask is empty."
    assert "half full" not in str(view)


@pytest.mark.parametrize(
    "identifier",
    [
        "OTHER_BAG_SECRET",
        "OTHER_INNER",
        "PLAYER_BAG_SECRET",
        "CONCEALED",
        "HIDDEN",
        "AWAY",
        "invented",
    ],
)
def test_unavailable_ids_have_uniform_response_and_never_become_sources(identifier):
    manager, rows = world()
    tools = tools_for(manager, rows)
    before = tools.mind
    assert inspect(tools, identifier) == {"status": "unavailable_entity"}
    assert tools.mind == before and not tools.pins
    assert identifier not in str(agent_observable.index(tools))


def test_visible_clothing_preserves_binding_and_excludes_private_properties():
    manager, rows = world()
    report = "The other coat's left sleeve has a square patch."
    secret = "The hidden lining contains a private serial number."
    save(
        manager,
        [
            proposal("OTHER_COAT", report, part="damage"),
            proposal(
                "OTHER_COAT", "A secret inscription.", part="inscription", visibility="private"
            ),
            proposal("OTHER_INNER", secret),
        ],
    )
    tools = tools_for(manager, rows)
    view = body(tools, "OTHER_COAT")
    assert view["owner_id"] == view["worn_by"] == "other"
    assert view["recorded_conditions"][0]["detail"] == report
    assert "secret inscription" not in str(view) and secret not in str(tools.observable.entities)
    assert "PRIVATE_METADATA" not in str(tools.observable.entities)
    assert "PRIVATE_SCRIPT" not in str(tools.observable.entities)
    assert body(tools, "PLAYER_COAT")["owner_id"] == "@player"


def test_private_own_state_is_available_only_to_its_observer():
    manager, rows = world()
    secret = "The flask contains my private mixture."
    save(manager, [proposal(detail=secret, visibility="private")])
    assert body(tools_for(manager, rows), "FLASK")["recorded_conditions"][0]["detail"] == secret
    other = tools_for(manager, rows, "other")
    assert inspect(other, "FLASK") == {"status": "unavailable_entity"}
    assert secret not in str(other.observable.entities)


def test_body_state_uses_own_knowledge_or_confirmed_visible_surface():
    manager, rows = world()
    visible = "A small bandage is visible on the forehead."
    save(
        manager,
        [
            proposal(
                "other",
                visible + " Private diagnosis.",
                kind="injury",
                part="head",
                visual_detail=visible,
                visual_region="head",
            ),
            proposal(
                "other",
                "A wound beneath the coat.",
                kind="injury",
                part="arm",
                visual_region="arms",
            ),
        ],
    )
    view = body(tools_for(manager, rows), "other")
    assert [row["detail"] for row in view["recorded_conditions"]] == [visible]
    assert "Private diagnosis" not in str(view)
    own = body(tools_for(manager, rows, "other"), "other")
    assert len(own["recorded_conditions"]) == 2 and "Private diagnosis" in str(own)


def test_fixed_room_object_is_readable_without_becoming_transferable():
    manager, rows = world()
    report = "The bell has a visible crack."
    save(manager, [proposal("BELL", report, part="damage")])
    before = deepcopy(vars(manager.state))
    view = body(tools_for(manager, rows), "BELL")
    assert view["recorded_conditions"][0]["detail"] == report
    assert view["owner_id"] == "__scene__" and vars(manager.state) == before


def test_placed_item_keeps_ownership_separate_from_physical_position():
    manager, rows = world()
    manager.state.entity_states[props.KEY] = {
        "items": [
            {
                "item_id": "FLASK",
                "owner_id": "npc",
                "scene_id": "room",
                "status": "confirmed",
                "visibility": "public",
                "spatial_position": "on the bench",
            }
        ]
    }
    save(manager, [proposal()])
    view = body(tools_for(manager, rows, "other"), "FLASK")
    assert view["owner_id"] == "npc" and view["spatial_position"] == "on the bench"
    assert view["recorded_conditions"][0]["detail"] == "The flask is half full."


@pytest.mark.parametrize(
    "field,value",
    [
        ("message_id", "later"),
        ("revision_id", "edited"),
        ("content_hash", "changed"),
        ("scene_id", "elsewhere"),
    ],
)
def test_stale_views_are_not_current_facts(field, value):
    manager, rows = world()
    tools = tools_for(manager, rows)
    tools.observation = tools.observation.model_copy(update={field: value})
    assert inspect(tools, "COAT") == {"status": "unavailable_entity"}
    assert agent_observable.index(tools) == {}


def test_cross_observer_and_session_views_cannot_be_reused():
    manager, rows = world()
    tools = tools_for(manager, rows)
    original = tools.observable
    for changes in [{"observer_id": "other"}, {"session_id": "other-session"}]:
        tools.observable = replace(original, **changes)
        assert inspect(tools, "FLASK") == {"status": "unavailable_entity"}
    rows.append(entity("FOREIGN", session_id="other-session"))
    assert "FOREIGN" not in observable_state.project(manager, rows, "npc", observation()).entities


@pytest.mark.parametrize("ledger", [None, {"version": 999}])
def test_missing_or_corrupt_state_is_unknown_not_a_clean_item(ledger):
    manager, rows = world()
    if ledger is not None:
        manager.state.entity_states[KEY] = ledger
    view = body(tools_for(manager, rows), "FLASK")
    assert view["recorded_conditions"] == [] and view["condition_knowledge"] == "unavailable"
    assert view["recorded_conditions_are_exhaustive"] is False


def test_view_and_index_budgets_declare_omissions_without_losing_canonical_facts():
    manager, rows = world()
    for index in range(12):
        save(
            manager,
            [proposal(detail="Observed " + "x" * 280, part=f"property_{index}")],
            f"m{index}",
        )
    tools = tools_for(manager, rows)
    extras = {
        f"ITEM_{i}": {"id": f"ITEM_{i}", "name": "Long name " * 15, "kind": "item"}
        for i in range(100)
    }
    tools.observable = replace(tools.observable, entities={**tools.observable.entities, **extras})
    index = agent_observable.index(tools)
    assert index["omitted_entities"] > 0
    assert len(json.dumps(index["observable_entities"], ensure_ascii=False)) <= 1500
    result = inspect(tools, "FLASK")
    assert len(result["text"]) <= 2000
    assert json.loads(result["text"])["omitted"]["recorded_conditions"] > 0
    assert len(read(manager.state.entity_states).conditions) == 12


def test_unknown_id_feedback_does_not_claim_the_item_does_not_exist():
    manager, rows = world()
    result = inspect(tools_for(manager, rows), "missing")
    feedback = tool_feedback.for_model("inspect_entity", result)
    assert feedback["status"] == "unavailable_entity"
    assert "does not prove absence" in feedback["message"]


def test_observing_an_item_never_grants_ownership_or_transfer_permission():
    from backend.engine.clothing.context import actor_records
    from backend.engine.narrated_items.apply import apply_actions
    from backend.engine.narrated_items.schema import ItemAction, ItemExtraction
    from backend.engine.visual_novel.continuity import possession_snapshot

    manager, rows = world()
    tools = tools_for(manager, rows)
    assert body(tools, "OTHER_COAT")["owner_id"] == "other"
    actors = actor_records(manager, rows)
    before = deepcopy(actors)
    narration = "The observer claims the coat is already theirs."
    action = ItemAction(
        item_id="OTHER_COAT",
        source_owner="npc",
        destination_owner="npc",
        disposition="carried",
        basis="completed",
        evidence=narration,
    )
    changed, accepted, errors = apply_actions(
        ItemExtraction(actions=[action]),
        actors,
        possession_snapshot(manager, rows),
        narration,
        detailed=False,
        session_id="session",
        message_id="reply",
    )
    assert not accepted and errors
    assert changed == before and actors == before
