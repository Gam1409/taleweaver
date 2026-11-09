"""Bystanders stay present without disabling one participant's confirmed changes."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.routes.adventures.logic import AdventureLogic
from backend.engine.narrated_items import runtime as items_runtime
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.scene_staging import runtime as staging_runtime
from backend.engine.scene_staging.schema import SceneExtraction
from backend.engine.scene_staging.state import KEY, project
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.engine.visual_novel.continuity import PLAYER


@pytest.fixture
def crowd(monkeypatch):
    people = [
        SimpleNamespace(
            id=f"N{index}",
            entity_type="NPC",
            name=f"Person {index}",
            current_scene_id="ROOM",
            inventory=[
                {
                    "id": f"item-{index}-{number}",
                    "name": f"Coin {index}/{number}",
                    "description": "A worn copper coin.",
                    "custom_origin": "retain-authoritative-data",
                }
                for number in range(6)
            ],
            equipment={},
            visual_profile=None,
            metadata_json={},
            is_hidden=False,
            is_defeated=False,
            description="",
            character="",
            goal="",
            session_id="SESSION",
        )
        for index in range(20)
    ]
    manager = SimpleNamespace(
        db=object(),
        game_id="SESSION",
        user=object(),
        _vn_player_message_id="TURN",
        avatar=SimpleNamespace(
            id="HERO", name="Hero", inventory=[], equipment={}, visual_profile=None
        ),
        state=SimpleNamespace(session_id="SESSION", current_scene_id="ROOM", entity_states={}),
    )
    write_settings(manager.state, VnSettings(scene_staging=True))
    for module in (items_runtime, staging_runtime):
        monkeypatch.setattr(module, "session_objects", AsyncMock(return_value=people))
        monkeypatch.setattr(module, "release_for_model", AsyncMock())
        monkeypatch.setattr(module, "role_timeout", lambda *_: 10)
    monkeypatch.setattr(items_runtime.scene_continuity, "prepare", AsyncMock(return_value={}))
    monkeypatch.setattr(
        AdventureLogic,
        "build_session_entities",
        AsyncMock(
            return_value=[
                {"id": person.id, "name": person.name, "entity_type": "NPC"} for person in people
            ]
        ),
    )
    return manager, people


async def test_one_transfer_in_a_twenty_npc_scene_keeps_every_other_inventory(monkeypatch, crowd):
    manager, people = crowd
    narration = "Person 0 hands the first coin to Hero."
    provider = AsyncMock(
        return_value=ItemExtraction.model_validate(
            {
                "actions": [
                    {
                        "item_id": "item-0-0",
                        "source_owner": "N0",
                        "destination_owner": PLAYER,
                        "basis": "completed",
                        "disposition": "carried",
                        "evidence": narration,
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(
        items_runtime.GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(model="mock", aexecute_complex_task=provider),
    )
    messages = await items_runtime.reconcile_items(
        manager, narration, completed=True, resolution=""
    )
    provider.assert_awaited_once()
    payload = json.loads(provider.await_args.args[1])
    assert len(payload["actors"]) == 21 and len(payload["items"]) == 120
    assert manager.avatar.inventory[0]["id"] == "item-0-0"
    assert manager.avatar.inventory[0]["custom_origin"] == "retain-authoritative-data"
    assert len(manager.state.entity_states["N0"]["inventory"]) == 5
    assert len(people[-1].inventory) == 6 and "N19" not in manager.state.entity_states
    assert messages and manager.state.entity_states[items_runtime.KEY]["status"] == "complete"


async def test_pose_update_in_crowded_scene_retains_bystander_facts_and_roster(monkeypatch, crowd):
    manager, _ = crowd
    narration = "Person 0 sits beside Person 19."
    manager.state.entity_states[KEY] = {
        "scene_id": "ROOM",
        "status": "ready",
        "actors": {
            "N19": {"origin": "", "posture": {"value": "standing", "evidence": "Earlier fact"}}
        },
    }
    provider = AsyncMock(
        return_value=SceneExtraction.model_validate(
            {
                "changes": [
                    {
                        "entity_id": "N0",
                        "posture": "sitting",
                        "evidence": narration,
                        "placement": {
                            "relation": "beside",
                            "target_kind": "character",
                            "target": "N19",
                        },
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(
        staging_runtime.GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(model="mock", aexecute_complex_task=provider),
    )
    await staging_runtime.reconcile_narration(manager, narration, completed=True)
    provider.assert_awaited_once()
    payload = json.loads(provider.await_args.args[1])
    assert len(payload["present_cast"]) == 21
    facts = project(manager.state, payload["present_cast"])
    assert facts["N0"]["posture"] == "sitting"
    assert facts["N0"]["placement"]["target"] == "N19"
    assert facts["N19"]["posture"] == "standing"


@pytest.mark.parametrize("module", [items_runtime, staging_runtime])
async def test_real_text_budget_still_refuses_without_sending_a_request(monkeypatch, crowd, module):
    manager, _ = crowd
    monkeypatch.setattr(module, "MAX_CONTEXT", 200, raising=False)
    provider = AsyncMock()
    monkeypatch.setattr(
        module.GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(model="mock", aexecute_complex_task=provider),
    )
    if module is items_runtime:
        await module.reconcile_items(manager, "Hero waits.", completed=True, resolution="")
    else:
        await module.reconcile_narration(manager, "Hero waits.", completed=True)
    provider.assert_not_awaited()
    assert "budget" in manager.state.entity_states[module.KEY]["reason"]
