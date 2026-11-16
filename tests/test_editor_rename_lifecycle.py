"""Authored renames preserve typed rules across transactions and session boundaries."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.editing.entity_update.rename_refs import renamed_references
from backend.api.routes.adventures.sessions import copy_session
from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.gameplay.world import AdventureLogic
from backend.engine.hard_rule_evaluator import HardRuleEvaluator, RuleEvaluationContext
from backend.engine.scripting.context import GameContext
from backend.engine.scripting.runner import ScriptRunner
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.session_entity_support import entity_world
from tests.test_editor_entity_update import _seed

__all__ = ["entity_world"]
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("trigger", [["extension"], {"extension": True}])
async def test_extension_metadata_without_a_script_trigger_remains_valid(trigger):
    source = {"metadata_json": {"extension": {"trigger": trigger, "target_id": "KEY"}}}
    assert renamed_references(source, "KEY", "BRASS_KEY", "entity") == source


@pytest.mark.parametrize("kind", ["entity", "scene"])
@pytest.mark.parametrize("trigger", ["on_enter_scene", "on_interact"])
async def test_script_target_rename_follows_its_typed_namespace(kind, trigger):
    source = {
        "scripts": [
            {
                "id": "CALLBACK",
                "trigger": trigger,
                "target_id": "SHARED",
                "code": "tw.vars.set('fired', True)",
            }
        ]
    }
    changed = renamed_references(source, "SHARED", "RENAMED", kind)
    expected = "RENAMED" if (kind == "scene") == (trigger == "on_enter_scene") else "SHARED"
    context = GameContext()
    ScriptRunner(changed["scripts"]).run_trigger(trigger, context, target_id=expected)
    assert context.changeset.var_updates == {"fired": True}


async def test_typed_reference_changes_keep_prose_sources_and_other_namespaces():
    source = {
        "objects": [
            {
                "id": "KEY",
                "description": "KEY",
                "metadata_json": {"on_pickup_script": "tw.objects.get('KEY').set_hidden(False)"},
            }
        ],
        "quests": [
            {
                "id": "KEY",
                "required_item_id": "KEY",
                "guard_expression": "tw.vars.get('KEY') == True",
            }
        ],
        "scripts": [
            {
                "id": "KEY",
                "trigger": "on_interact",
                "target_id": "KEY",
                "code": "tw.objects.get('KEY').set_hidden(False)",
            },
            {
                "id": "SEQUENCE",
                "trigger": "on_end_sequence",
                "target_id": "KEY",
                "code": "tw.vars.set('KEY', 1)",
            },
        ],
        "protagonist": {
            "starting_inventory": ["KEY", {"id": "KEY", "name": "KEY"}],
            "starting_equipment": {"Main_Hand": {"id": "KEY"}},
        },
        "switch": {
            "transitions": [
                {"gates": {"item": "KEY", "code": "KEY", "expression": "tw.vars.get('KEY')"}}
            ],
            "outcomes": [
                {
                    "effects": [
                        {"type": "story_flag", "key": "KEY"},
                        {"type": "unlock_container", "target_id": "KEY"},
                        {"type": "unlock_exit", "target_id": "stable-exit"},
                    ]
                }
            ],
        },
    }
    before = deepcopy(source)
    changed = renamed_references(source, "KEY", "BRASS_KEY", "entity")
    assert source == before
    assert changed["objects"][0]["id"] == "BRASS_KEY"
    assert changed["objects"][0]["description"] == "KEY"
    assert changed["objects"][0]["metadata_json"] == source["objects"][0]["metadata_json"]
    assert changed["quests"][0] == {**source["quests"][0], "required_item_id": "BRASS_KEY"}
    assert changed["scripts"][0] == {**source["scripts"][0], "target_id": "BRASS_KEY"}
    assert changed["scripts"][1] == source["scripts"][1]
    assert changed["protagonist"]["starting_inventory"] == [
        "BRASS_KEY",
        {"id": "BRASS_KEY", "name": "KEY"},
    ]
    assert changed["protagonist"]["starting_equipment"]["Main_Hand"]["id"] == "BRASS_KEY"
    assert changed["switch"]["transitions"][0]["gates"] == {
        "item": "BRASS_KEY",
        "code": "KEY",
        "expression": "tw.vars.get('KEY')",
    }
    assert changed["switch"]["outcomes"][0]["effects"] == [
        {"type": "story_flag", "key": "KEY"},
        {"type": "unlock_container", "target_id": "BRASS_KEY"},
        {"type": "unlock_exit", "target_id": "stable-exit"},
    ]
    assert HardRuleEvaluator.evaluate_target(
        {"required_item_id": changed["quests"][0]["required_item_id"]},
        RuleEvaluationContext(inventory_item_ids={"BRASS_KEY"}),
    )
    scene = renamed_references(
        {
            "effects": [
                {"type": "unlock_exit", "target_id": "stable-exit"},
                {"type": "story_flag", "key": "HALL:YARD"},
            ],
            "description": "HALL:YARD",
        },
        "HALL",
        "GREAT_HALL",
        "scene",
    )
    assert scene == {
        "effects": [
            {"type": "unlock_exit", "target_id": "stable-exit"},
            {"type": "story_flag", "key": "HALL:YARD"},
        ],
        "description": "HALL:YARD",
    }


@pytest.mark.parametrize("kind", ["entity", "scene"])
async def test_late_validation_failure_rolls_back_rename_and_all_references(
    auth_client, setup_test_db, kind
):
    template = await _seed()
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template)
        adventure.sequences = [
            {"id": "CHAPTER", "required_defeated_npc_id": "GUARD", "required_scene_id": "HALL"}
        ]
        adventure.original_manifest = {
            **adventure.original_manifest,
            "sequences": deepcopy(adventure.sequences),
        }
        await db.commit()
    payload = {
        "target_type": "npc",
        "target_id": "GUARD",
        "new_id": "SENTINEL",
        "current_scene_id": "MISSING",
    }
    if kind == "scene":
        payload = {
            "target_type": "scene",
            "target_id": "HALL",
            "new_id": "GREAT_HALL",
            "decorative_objects": ["x" * 101],
        }
    response = await auth_client.patch(f"/api/adventures/{template}/editor/entity", json=payload)
    assert response.status_code == 400, response.text
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template)
        assert adventure.sequences == [
            {"id": "CHAPTER", "required_defeated_npc_id": "GUARD", "required_scene_id": "HALL"}
        ]
        assert adventure.original_manifest["sequences"] == adventure.sequences
        guide = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.template_id == template, WorldEntity.session_id.is_(None)
            )
        )
        assert (guide.id, guide.current_scene_id) == ("GUARD", "HALL")


async def test_renamed_template_starts_with_current_rules_and_saved_sessions_remain_independent(
    entity_world,
):
    world = entity_world
    db = world.db
    template = world.template
    template.sequences = [
        {
            "id": "CHAPTER",
            "title": "Archive",
            "order": 1,
            "required_item_id": "TOKEN",
            "required_scene_id": "ROOM",
            "required_defeated_npc_id": "GUIDE",
        }
    ]
    template.original_manifest = {
        **template.original_manifest,
        "sequences": deepcopy(template.sequences),
        "scripts": [
            {
                "id": "ARRIVE",
                "trigger": "on_enter_scene",
                "target": "ROOM",
                "code": "tw.vars.set('visited', True)",
            }
        ],
    }
    guide = await db.scalar(
        select(WorldEntity).where(
            WorldEntity.template_id == template.id,
            WorldEntity.session_id.is_(None),
            WorldEntity.id == "GUIDE",
        )
    )
    guide.metadata_json = {
        **guide.metadata_json,
        "attack_trigger": {"required_item_id": "TOKEN", "required_scene_id": "ROOM"},
    }
    source = await db.scalar(select(SessionState).where(SessionState.session_id == world.source.id))
    source.entity_states = {
        **source.entity_states,
        AdventureLogic.SESSION_MANIFEST_SNAPSHOT_KEY: AdventureLogic.build_session_manifest_snapshot(
            template
        ),
    }
    before = deepcopy(source.entity_states)
    await db.commit()
    for target_type, old, new in [
        ("object", "TOKEN", "SEAL"),
        ("npc", "GUIDE", "SENTINEL"),
        ("scene", "ROOM", "ARCHIVE"),
    ]:
        response = await world.client.patch(
            f"/api/adventures/{template.id}/editor/entity",
            json={"target_type": target_type, "target_id": old, "new_id": new},
        )
        assert response.status_code == 200, response.text
    await db.refresh(template)
    exported = await AdventureExporter.build_full_manifest(db, template.id)
    assert exported["sequences"][0]["required_item_id"] == "SEAL"
    assert exported["sequences"][0]["required_scene_id"] == "ARCHIVE"
    assert exported["sequences"][0]["required_defeated_npc_id"] == "SENTINEL"
    assert exported["scripts"][0]["target"] == "ARCHIVE"
    context = RuleEvaluationContext(
        current_scene_id="ARCHIVE", inventory_item_ids={"SEAL"}, defeated_npc_ids={"SENTINEL"}
    )
    assert HardRuleEvaluator.evaluate_target(exported["sequences"][0], context)
    started = await world.client.post(f"/api/adventures/{template.id}/sessions/start")
    assert started.status_code == 201, started.text
    fresh = await db.scalar(
        select(SessionState).where(SessionState.session_id == started.json()["game_id"])
    )
    assert (
        fresh.entity_states[AdventureLogic.SESSION_MANIFEST_SNAPSHOT_KEY]["adventure"]["sequences"][
            0
        ]
        == exported["sequences"][0]
    )
    assert fresh.current_scene_id == "ARCHIVE"
    npc = await db.scalar(
        select(WorldEntity).where(
            WorldEntity.session_id == fresh.session_id, WorldEntity.id == "SENTINEL"
        )
    )
    assert npc.allowed_scenes == ["ARCHIVE"]
    assert npc.metadata_json["attack_trigger"] == {
        "required_item_id": "SEAL",
        "required_scene_id": "ARCHIVE",
    }
    copied = await copy_session(fresh.session_id, db, world.owner)
    saved_copy = await db.scalar(
        select(SessionState).where(SessionState.session_id == copied["game_id"])
    )
    assert (
        saved_copy.entity_states[AdventureLogic.SESSION_MANIFEST_SNAPSHOT_KEY]
        == fresh.entity_states[AdventureLogic.SESSION_MANIFEST_SNAPSHOT_KEY]
    )
    await db.refresh(source)
    assert source.entity_states == before
    old_npc = await db.scalar(
        select(WorldEntity).where(
            WorldEntity.session_id == source.session_id, WorldEntity.id == "GUIDE"
        )
    )
    assert old_npc.allowed_scenes == ["ROOM"]
