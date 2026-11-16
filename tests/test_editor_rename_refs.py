"""Editor renames preserve the authored rules and executable switch references."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.editing.entity_update.rename_refs import renamed_references
from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.scripting.context import GameContext
from backend.models.adventure_template import AdventureTemplate
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_editor_entity_update import _seed

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("target", ["HALL:YARD", "YARD:HALL"])
async def test_scene_rename_preserves_scripted_switch_exit_outcomes(target):
    definitions = {
        "SWITCH": {
            "id": "SWITCH",
            "entity_type": "OBJECT",
            "metadata_json": {
                "switch": {
                    "states": ["OFF", "ON"],
                    "initial_state": "OFF",
                    "outcomes": [
                        {
                            "on_state": "ON",
                            "effects": [{"type": "unlock_exit", "target_id": target}],
                        }
                    ],
                }
            },
        }
    }
    before = GameContext(entities=definitions, exit_states={target: {"is_locked": True}})
    before.switches.set_state("SWITCH", "ON")
    assert before.changeset.exit_updates[0]["from_scene_id"] == target.split(":")[0]
    changed = renamed_references(definitions, "HALL", "GREAT_HALL", "scene")
    after = GameContext(entities=changed)
    after.switches.set_state("SWITCH", "ON")
    expected = ["GREAT_HALL" if part == "HALL" else part for part in target.split(":")]
    assert after.changeset.exit_updates == [
        {"from_scene_id": expected[0], "to_scene_id": expected[1], "is_locked": False}
    ]


async def test_rename_cascades_rule_references(auth_client, setup_test_db):
    template = await _seed()
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template)
        adventure.quests = [{"id": "VISIT", "required_scene_id": "HALL"}]
        adventure.sequences = [
            {"id": "COLLECT", "required_item_id": "KEY", "required_scene_id": "HALL"}
        ]
        manifest = deepcopy(adventure.original_manifest)
        manifest.update(
            start_scene_id="HALL",
            scenes=[{"id": "HALL", "label": "Hall"}, {"id": "YARD", "label": "Yard"}],
            quests=deepcopy(adventure.quests),
            sequences=deepcopy(adventure.sequences),
            scripts=[
                {
                    "id": "ARRIVE",
                    "trigger": "on_enter_scene",
                    "target_id": "HALL",
                    "code": "tw.vars.set('arrived', True)",
                }
            ],
        )
        adventure.original_manifest = manifest
        guide = await db.scalar(select(WorldEntity).where(WorldEntity.id == "GUARD"))
        guide.allowed_scenes = ["HALL", "YARD"]
        db.add_all(
            [
                WorldEntity(
                    id="KEY",
                    template_id=template,
                    entity_type="OBJECT",
                    name="Key",
                    description="A key",
                    current_scene_id="HALL",
                ),
                WorldEntity(
                    id="LEVER",
                    template_id=template,
                    entity_type="OBJECT",
                    item_type="SWITCH",
                    name="Lever",
                    description="A lever",
                    current_scene_id="HALL",
                    metadata_json={
                        "switch": {
                            "states": ["OFF", "ON"],
                            "initial_state": "OFF",
                            "outcomes": [
                                {
                                    "on_state": "ON",
                                    "effects": [{"type": "unlock_exit", "target_id": "HALL:YARD"}],
                                }
                            ],
                        }
                    },
                ),
                WorldEntity(
                    id="CHEST",
                    template_id=template,
                    entity_type="OBJECT",
                    name="Chest",
                    description="A chest",
                    current_scene_id="HALL",
                    item_type="CONTAINER",
                    metadata_json={"item_to_unlock": "KEY"},
                ),
            ]
        )
        await db.commit()
    item = await auth_client.patch(
        f"/api/adventures/{template}/editor/entity",
        json={"target_type": "object", "target_id": "KEY", "new_id": "BRASS_KEY"},
    )
    scene = await auth_client.patch(
        f"/api/adventures/{template}/editor/entity",
        json={"target_type": "scene", "target_id": "HALL", "new_id": "GREAT_HALL"},
    )
    assert item.status_code == scene.status_code == 200
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template)
        guide = await db.scalar(select(WorldEntity).where(WorldEntity.id == "GUARD"))
        chest = await db.scalar(select(WorldEntity).where(WorldEntity.id == "CHEST"))
        exported = await AdventureExporter.build_full_manifest(db, template)
        lever = next(item for item in exported["objects"] if item["id"] == "LEVER")
        assert lever["switch_outcomes"][0]["effects"][0]["target_id"] == "GREAT_HALL:YARD"
        assert adventure.original_manifest["scenes"][0]["id"] == "GREAT_HALL"
        evidence = dict(
            sequence=adventure.sequences,
            quest=adventure.quests,
            script=adventure.original_manifest["scripts"],
            allowed_scenes=guide.allowed_scenes,
            chest_key=chest.metadata_json["item_to_unlock"],
            exported_sequence=exported["sequences"],
        )
        print("RENAME_EVIDENCE", json.dumps(evidence, sort_keys=True))
        assert evidence["chest_key"] == "BRASS_KEY"
        assert adventure.sequences[0]["required_item_id"] == "BRASS_KEY"
        assert adventure.quests[0]["required_scene_id"] == "GREAT_HALL"
        assert adventure.original_manifest["scripts"][0]["target_id"] == "GREAT_HALL"
        assert guide.allowed_scenes == ["GREAT_HALL", "YARD"]
