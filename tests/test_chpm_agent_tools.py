"""Agent reads stay inside one observer/session and retain original source identities."""

import json
from types import SimpleNamespace

import pytest

from backend.engine.chpm import agent_views, appraisal_context, host_observations
from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.host_observation_contracts import HostFacts, Possession
from backend.engine.chpm.host_state import before_messages, record
from backend.engine.chpm.kernel import ChpmError
from tests.test_chpm_host_state import mind, source
from tests.test_chpm_kernel import observation
from tests.test_clothing_core import item, profile


def current(value=None):
    facts = HostFacts(
        scene_id="room", visible_actor_ids=("other",), owned_items=(Possession(id="key"),)
    )
    frame = source("input", host_observations.frame(facts), "host_frame").model_copy(
        update={"facts": facts}
    )
    return record(value or mind(), frame, minute=5)


def test_rag_searches_old_observed_sources_and_pins_exact_excerpt_without_new_memory():
    value = record(
        mind(), source("old", "The amber locker holds a cobalt compass, code 7319."), minute=0
    )
    for n in range(40):
        value = record(value, source(f"later{n}", f"Routine report number {n}."), minute=1)
    original = value.model_dump_json()
    tools = Tools(value, observation(), {})
    result = tools.execute(Lookup(tool="search_memory", argument="cobalt compass"))
    assert result["mode"] == "lexical_observer_rag"
    assert result["matches"] == 1
    hit = result["results"][0]
    assert hit["source_message_id"] == "old" and "7319" in hit["text"]
    assert not hit["current_turn"] and hit["kind"] == "reported"
    window = appraisal_context.build(value, recent_limit=1, recall_limit=0, pinned=tools.pins)
    assert window.sources[hit["source_id"]][2] == hit["text"]
    assert value.model_dump_json() == original
    assert tools.execute(Lookup(tool="search_memory", argument="nonexistent"))["results"] == []
    assert (
        tools.execute(Lookup(tool="read_memory", argument=hit["memory_id"]))["text"] == hit["text"]
    )


def test_source_handles_cannot_read_another_session_or_unexposed_record():
    first = current(record(mind(), source(text="public key"), minute=1))
    second = current(record(mind(session="other-session"), source(text="secret key"), minute=1))
    first_tools = Tools(first, observation(), {})
    second_tools = Tools(second, observation(session_id="other-session"), {})
    hit = second_tools.search("secret")["results"][0]
    assert first_tools.execute(Lookup(tool="read_memory", argument=hit["memory_id"])) == {
        "status": "unavailable_source"
    }
    assert first_tools.search("secret")["results"] == []
    with pytest.raises(ChpmError, match="another session"):
        Tools(second, observation(), {})
    assert (
        Tools(before_messages(first, {"m1"}), observation(), {}).search("public")["results"] == []
    )


def test_current_self_and_visible_clothing_are_known_only_at_the_current_boundary():
    view = {
        "other": {
            "status": "known",
            "name": "Other",
            "clothing": [{"item_id": "coat", "layer": 3}],
            "omitted": 0,
        }
    }
    tools = Tools(current(), observation(), view)
    assert '"key"' in tools.execute(Lookup(tool="inspect_self"))["text"]
    assert (
        tools.execute(Lookup(tool="visible_clothing", argument="absent"))["status"]
        == "unavailable_actor"
    )
    original = tools.mind
    result = tools.execute(Lookup(tool="visible_clothing", argument="other"))
    assert json.loads(result["text"])["clothing"][0]["layer"] == 3
    assert len(tools.mind.sources) == len(original.sources) + 1
    assert tools.mind.genesis == original.genesis
    assert result["source_id"] in appraisal_context.build(tools.mind, pinned=tools.pins).sources
    stale = Tools(tools.mind, observation(message_id="later"), view)
    assert stale.execute(Lookup(tool="inspect_self"))["status"] == "unknown"
    assert (
        stale.execute(Lookup(tool="visible_clothing", argument="other"))["status"]
        == "unavailable_actor"
    )


def clothing_actor():
    return SimpleNamespace(
        id="other",
        name="Other",
        inventory=[item("hidden", 1, ["torso"]), item("coat", 3, ["torso"])],
        metadata_json={},
        visual_profile=profile("hidden", "coat", age=30),
        age_years=30,
        entity_type="NPC",
        current_scene_id="room",
        is_hidden=False,
        is_defeated=False,
    )


def test_projection_never_exposes_covered_layers_or_carried_items_and_respects_displacement():
    actor = clothing_actor()
    actor.inventory.append(item("carried-secret", 4, ["torso"]))
    state = SimpleNamespace(current_scene_id="room", entity_states={})
    view = agent_views.project(actor, state, [])
    assert [g["item_id"] for g in view["clothing"]] == ["coat"]
    assert view["clothing"][0]["layer"] == 3
    assert "hidden" not in str(view) and "carried-secret" not in str(view)
    actor.visual_profile["worn"][1].update(uncovered_regions=["torso"])
    view = agent_views.project(actor, state, [])
    assert [g["item_id"] for g in view["clothing"]] == ["hidden"]
    actor.inventory = []
    assert agent_views.project(actor, state, [])["status"] == "unknown"


def test_projection_uses_canonical_items_and_session_overrides():
    actor = clothing_actor()
    canonical = SimpleNamespace(
        id="coat",
        name="Canonical coat",
        description="",
        metadata_json={"clothing": item("coat", 3, ["torso"])["clothing"]},
        entity_type="OBJECT",
    )
    state = SimpleNamespace(
        current_scene_id="room", entity_states={"coat": {"name": "Session coat"}}
    )
    view = agent_views.project(actor, state, [canonical])
    assert view["clothing"][0]["name"] == "Session coat"


async def test_capture_is_scoped_to_game_id_and_excludes_absent_and_hidden_npcs(monkeypatch):
    from unittest.mock import AsyncMock

    visible = clothing_actor()
    hidden = SimpleNamespace(**{**vars(visible), "id": "hidden", "is_hidden": True})
    absent = SimpleNamespace(**{**vars(visible), "id": "absent", "current_scene_id": "elsewhere"})
    mock = AsyncMock(return_value=[visible, hidden, absent])
    monkeypatch.setattr(agent_views, "session_objects", mock)
    manager = SimpleNamespace(
        db=object(),
        game_id="session-A",
        state=SimpleNamespace(current_scene_id="room", entity_states={}),
    )
    assert set(await agent_views.capture(manager)) == {"other"}
    mock.assert_awaited_once_with(manager.db, "session-A")


def test_read_expands_only_previously_exposed_source_and_respects_pinned_budget():
    value = mind()
    for index in range(4):
        value = record(value, source(f"large{index}", f"needle{index} " + "known " * 320), minute=1)
    tools = Tools(value, observation(), {})
    for index in range(3):
        hit = tools.search(f"needle{index}")["results"][0]
        expanded = tools.execute(Lookup(tool="read_memory", argument=hit["memory_id"]))
        assert len(hit["text"]) == 600 and len(expanded["text"]) > 1800
        assert expanded["source_id"] == hit["source_id"] and not expanded["excerpted"]
    fourth = tools.search("needle3")["results"][0]
    assert fourth["status"] == "evidence_budget_exhausted"
    assert len(tools.pins) == 3


def test_clothing_detail_settings_apply_after_occlusion_and_unknown_age_is_not_guessed():
    actor = clothing_actor()
    actor.inventory = [item("inner", 0, ["torso"], underwear=True)]
    actor.visual_profile = profile("inner", age=30)
    state = SimpleNamespace(current_scene_id="room", entity_states={})
    assert agent_views.project(actor, state, [])["clothing"] == []
    state.entity_states = {
        "__manifest_snapshot__": {"original_manifest": {"clothing_settings": {"detailed": True}}}
    }
    assert agent_views.project(actor, state, [])["clothing"][0]["layer"] == 0
    actor.age_years = None
    actor.visual_profile = profile("inner")
    assert agent_views.project(actor, state, [])["clothing"] == []


def test_search_does_not_return_the_current_question_as_an_old_memory():
    value = record(mind(), source("old", "The cabinet code is 7319."), minute=1)
    value = record(value, source("input", "Where is the blue navigation instrument?"), minute=2)
    tools = Tools(value, observation(), {})
    assert tools.search("blue navigation instrument")["results"] == []
    result = tools.search("cabinet code")["results"]
    assert len(result) == 1 and result[0]["source_message_id"] == "old"
    assert "7319" in result[0]["text"]


@pytest.mark.parametrize(
    "opaque,expected", [(False, {"sweater", "jeans", "bra"}), (True, {"sweater", "jeans"})]
)
def test_red_underwear_visibility_under_sweater_and_jeans(opaque, expected):
    actor = clothing_actor()
    actor.inventory = [
        item("bra", 0, ["torso"], underwear=True),
        item("briefs", 0, ["pelvis"], underwear=True),
        item("jeans", 2, ["pelvis", "legs"]),
        item("sweater", 2, ["torso", "arms"], opaque=opaque),
    ]
    actor.inventory[0]["name"] = "Red bra"
    actor.inventory[1]["name"] = "Red briefs"
    actor.visual_profile = profile("bra", "briefs", "jeans", "sweater", age=30)
    state = SimpleNamespace(
        current_scene_id="room",
        entity_states={
            "__manifest_snapshot__": {
                "original_manifest": {"clothing_settings": {"detailed": True}}
            }
        },
    )
    view = agent_views.project(actor, state, [])
    assert {garment["item_id"] for garment in view["clothing"]} == expected
    assert "Red briefs" not in str(view)
    assert ("Red bra" in str(view)) is not opaque
