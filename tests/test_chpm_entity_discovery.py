"""Discovery searches the scoped view rather than the truncated prompt index."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from backend.engine.chpm import agent_observable, tool_feedback
from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.native_tool_contracts import parse_call
from tests.observable_state_support import entity, tools_for, world


def search(tools, query):
    return tools.execute(Lookup(tool="find_entity", argument=query))


def test_find_then_inspect_reuses_the_exact_id_beyond_the_initial_index():
    manager, rows = world()
    rows += [entity(f"OBJECT_{index:03}") for index in range(100)]
    rows.append(entity("Z_LAST", name="Старинный компас"))
    tools = tools_for(manager, rows)
    before = deepcopy(vars(manager.state))
    assert "Z_LAST" not in str(agent_observable.index(tools))
    result = search(tools, "КОМПАС")
    assert result["status"] == "ok" and result["matches"] == 1
    assert result["results"] == [{"id": "Z_LAST", "name": "Старинный компас", "kind": "item"}]
    assert not tools.pins  # Handles are discovery metadata, not action evidence.
    request = parse_call("inspect_entity", json.dumps({"argument": result["results"][0]["id"]}))
    assert json.loads(tools.execute(request)["text"])["id"] == "Z_LAST"
    assert vars(manager.state) == before


@pytest.mark.parametrize("query", ["HIDDEN", "OTHER_BAG_SECRET", "PLAYER_BAG_SECRET", "AWAY"])
def test_discovery_does_not_search_the_global_identity_catalog(query):
    manager, rows = world()
    tools = tools_for(manager, rows)
    assert search(tools, query) == {
        "status": "ok",
        "matches": 0,
        "omitted_matches": 0,
        "results": [],
    }
    assert not tools.pins


def test_discovery_reports_all_matches_and_keeps_ambiguous_names_distinct():
    manager, rows = world()
    rows += [entity(f"COMPASS_{index}", name="Compass") for index in range(20)]
    tools = tools_for(manager, rows)
    result = search(tools, "compass")
    assert result["matches"] == 20 and len(result["results"]) == 8
    assert result["omitted_matches"] == 12
    assert len({row["id"] for row in result["results"]}) == 8
    exact = search(tools, "COMPASS_19")
    assert exact["results"][0]["id"] == "COMPASS_19"
    assert len(json.dumps(result, ensure_ascii=False)) <= 2000


def test_stale_discovery_is_unavailable_rather_than_an_empty_world():
    manager, rows = world()
    tools = tools_for(manager, rows)
    tools.observable = replace(tools.observable, revision_id="changed")
    assert search(tools, "FLASK") == {"status": "unavailable_view"}


def test_wrong_clothing_tool_explains_the_player_inspection_path_without_revealing_state():
    manager, rows = world()
    tools = tools_for(manager, rows)
    raw = tools.execute(Lookup(tool="visible_clothing", argument="@player"))
    assert raw == {"status": "unavailable_actor"}
    feedback = tool_feedback.for_model("visible_clothing", raw)
    assert "inspect_entity" in feedback["message"] and "@player" in feedback["message"]
    assert "PLAYER_BAG_SECRET" not in str(feedback)
    assert not tools.pins


def test_scene_read_is_citable_but_contains_no_other_private_state():
    manager, rows = world()
    tools = tools_for(manager, rows)
    tools.observable = replace(
        tools.observable,
        scene={"description": "A quiet room.", "routes_knowledge": "unavailable"},
    )
    before = deepcopy(vars(manager.state))
    result = tools.execute(parse_call("inspect_scene", "{}"))
    body = json.loads(result["text"])
    assert body["scene_id"] == "room" and body["description"] == "A quiet room."
    assert {row["id"] for row in body["visible_actors"]} == {"npc", "other", "@player"}
    assert "OTHER_BAG_SECRET" not in result["text"]
    assert body["recorded_facts_are_exhaustive"] is False
    assert body["scene_knowledge"] == "unavailable"
    assert body["routes_knowledge"] == "unavailable"
    assert result["source_id"] in tools.pins and vars(manager.state) == before


def test_scene_budget_reports_omitted_routes_without_mutating_the_snapshot():
    manager, rows = world()
    tools = tools_for(manager, rows)
    routes = [
        {"scene_id": f"r{index}", "label": "Long label " * 20, "locked": False}
        for index in range(30)
    ]
    tools.observable = replace(tools.observable, scene={"routes": routes})
    result = tools.execute(parse_call("inspect_scene", "{}"))
    body = json.loads(result["text"])
    assert len(result["text"]) <= 2000
    assert len(body["routes"]) + body["omitted"]["routes"] == 30
    assert len(tools.observable.scene["routes"]) == 30


def test_unavailable_scene_does_not_become_a_new_observation():
    manager, rows = world()
    tools = tools_for(manager, rows)
    tools.observable = None
    assert tools.execute(parse_call("inspect_scene", "{}")) == {"status": "unavailable_view"}
    assert not tools.pins
