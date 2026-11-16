"""Shared staging keeps existing identity, validation and lifecycle boundaries."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.engine.narrated_items.schema import ItemExtraction, SharedItemExtraction
from backend.engine.scene_staging import bindings, props, shared
from backend.engine.scene_staging.schema import SceneExtraction
from backend.engine.scene_staging.state import KEY, narration_block
from backend.engine.visual_novel.continuity import PLAYER
from tests.test_narrated_items import fixtures


@pytest.mark.parametrize(
    "identity,valid",
    [
        ({"item_id": "ITEM"}, True),
        ({"item_action_index": 0}, True),
        ({"item_id": "ITEM", "item_action_index": 0}, False),
        ({}, False),
        ({"item_action_index": 6}, False),
        ({"item_action_index": True}, False),
    ],
)
def test_prop_identity_wire_and_host_agree(identity, valid):
    payload = {"owner_id": PLAYER, "evidence": "Hero puts it down.", **identity}
    assert Draft202012Validator(props.PropDelta.model_json_schema()).is_valid(payload) is valid
    if valid:
        value = props.PropDelta.model_validate(payload)
        assert props.PropDelta.model_validate_json(value.model_dump_json()) == value
        return
    with pytest.raises(ValidationError):
        props.PropDelta.model_validate(payload)


def test_shared_transport_does_not_relax_item_application_or_disabled_schema():
    invalid = {"actions": [{"new_item": {"name": "Incomplete"}}], "staging": {}}
    shared_value = SharedItemExtraction.model_validate(invalid)
    assert shared_value.staging == {}
    with pytest.raises(ValidationError):
        ItemExtraction.model_validate(shared_value.model_dump(exclude={"staging"}))
    assert "staging" not in ItemExtraction.model_json_schema()["properties"]
    assert not Draft202012Validator(SharedItemExtraction.model_json_schema()).is_valid(invalid)


def test_alias_binding_and_action_references_do_not_mutate_proposal():
    extraction = SceneExtraction.model_validate(
        {
            "changes": [
                {
                    "entity_id": PLAYER,
                    "placement": {
                        "relation": "beside",
                        "target_kind": "character",
                        "target": "NPC",
                    },
                    "evidence": "Hero stands beside Anna.",
                }
            ],
            "props": [
                {"owner_id": PLAYER, "item_action_index": index, "evidence": "Hero puts it down."}
                for index in [0, 1]
            ],
        }
    )
    before = extraction.model_dump()
    bound, rejected = bindings.resolve(
        extraction, "hero", [{"action_index": 1, "item": {"id": "NEW"}}]
    )
    assert rejected == 1 and len(bound.props) == 1
    assert bound.props[0].item_id == "NEW" and bound.props[0].owner_id == "hero"
    assert bound.props[0].item_action_index is None and bound.changes[0].entity_id == "hero"
    assert extraction.model_dump() == before


def test_previous_scene_aliases_keep_literal_object_names_and_source_unchanged():
    previous = {
        "NPC": {"placement": {"relation": "near", "target_kind": "character", "target": "hero"}},
        "hero": {
            "placement": {"relation": "near", "target_kind": "scene_object", "target": "hero"}
        },
    }
    saved = deepcopy(previous)
    people, projected = bindings.input_cast([{"id": "hero"}, {"id": "NPC"}], previous, "hero")
    assert people[0]["id"] == PLAYER
    assert projected["NPC"]["placement"]["target"] == PLAYER
    assert projected[PLAYER]["placement"]["target"] == "hero"
    assert previous == saved


def manager():
    actors, _ = fixtures()
    avatar = SimpleNamespace(**{**actors[PLAYER], "id": "hero"})
    npc = SimpleNamespace(
        **{
            **actors["NPC"],
            "entity_type": "NPC",
            "current_scene_id": "ROOM",
            "spatial_position": None,
            "metadata_json": {},
            "is_hidden": False,
            "is_defeated": False,
        }
    )
    state = SimpleNamespace(
        current_scene_id="ROOM",
        session_id="session",
        entity_states={"__vn_settings__": {"scene_staging": True}},
    )
    return SimpleNamespace(state=state, avatar=avatar), actors, [npc]


@pytest.mark.parametrize("changed", ["source", "scene", "position"])
def test_changed_source_or_scope_cannot_confirm_an_old_pose(changed):
    current, actors, rows = manager()
    text = "Anna sits down."
    assert shared.begin(current, text)
    shared.prepare(current, actors, rows)
    shared.propose(
        current,
        {"staging": {"changes": [{"entity_id": "NPC", "posture": "sitting", "evidence": text}]}},
    )
    if changed == "scene":
        current.state.current_scene_id = "OTHER"
    if changed == "position":
        current.state.entity_states["NPC"] = {"spatial_position": "near the door"}
    assert shared.consume(
        current, "Different narration." if changed == "source" else text, completed=True
    )
    assert current.state.entity_states[KEY]["status"] == "unconfirmed"
    assert not current.state.entity_states[KEY]["actors"]


def test_stale_result_does_not_overwrite_a_newer_staging_registry():
    current, actors, rows = manager()
    shared.begin(current, "Anna sits down.")
    shared.prepare(current, actors, rows)
    shared.propose(current, {"staging": {}})
    newer = {"status": "ready", "actors": {"NPC": {"posture": {"value": "standing"}}}}
    current.state.entity_states[KEY] = deepcopy(newer)
    assert shared.consume(current, "Anna sits down.", completed=True)
    assert current.state.entity_states[KEY] == newer


def test_hidden_embedded_inventory_item_is_not_a_narrator_prop():
    current, _, rows = manager()
    current.avatar.inventory = [{"id": "SECRET", "name": "Secret document", "is_hidden": True}]
    current.state.entity_states[props.KEY] = {
        "items": [
            {
                "item_id": "SECRET",
                "owner_id": "hero",
                "name": "Secret document",
                "scene_id": "ROOM",
                "status": "confirmed",
                "spatial_position": "on the shelf",
            }
        ]
    }
    assert "Secret document" not in narration_block(current.state, rows, current.avatar)
    assert not props.candidates(current.avatar, rows, current.state, set(), include_worn=True)


async def test_standalone_adapter_cancellation_keeps_its_invalidation_contract(monkeypatch):
    from backend.engine.gameplay.world import AdventureLogic
    from backend.engine.scene_staging import runtime

    current, _, rows = manager()
    current.db, current.user, current.game_id = object(), object(), "session"
    current.state.entity_states[KEY] = {"scene_id": "ROOM", "status": "ready", "actors": {}}
    monkeypatch.setattr(
        AdventureLogic,
        "build_session_entities",
        AsyncMock(return_value=[{"id": "NPC", "entity_type": "NPC", "name": "Anna"}]),
    )
    monkeypatch.setattr(runtime, "session_objects", AsyncMock(return_value=rows))
    monkeypatch.setattr(runtime, "release_for_model", AsyncMock())
    monkeypatch.setattr(runtime, "role_timeout", lambda *_: 10)
    monkeypatch.setattr(
        runtime.GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(
            model="local", aexecute_complex_task=AsyncMock(side_effect=asyncio.CancelledError())
        ),
    )
    with pytest.raises(asyncio.CancelledError):
        await runtime.reconcile_narration(current, "Anna waits.", completed=True)
    assert current.state.entity_states[KEY]["status"] == "unconfirmed"
