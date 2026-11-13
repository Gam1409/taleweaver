"""Editor reads and unrelated saves preserve the switch runtime's global callbacks."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from backend.engine.scripting.context import GameContext
from backend.engine.scripting.runner import ScriptRunner
from backend.engine.switch_service import SwitchService
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.editor_entity_creation_support import entity_creation_world, entity_payload

__all__ = ["entity_creation_world"]
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("representation", ["flat", "missing", "empty", "current"])
async def test_switch_globals_survive_assets_read_name_edit_and_runtime(
    entity_creation_world, representation
):
    world = entity_creation_world
    config = {"states": ["OFF", "ON"], "initial_state": "OFF", "transitions": []}
    metadata = {
        "on_success_script": "tw.vars.set('stale_success', True)",
        "on_failure_script": "tw.vars.set('stale_failure', True)",
        "switch_states": ["OFF", "ON"],
        "switch_initial_state": "OFF",
        "switch": config,
    }
    if representation in {"empty", "current"}:
        config.update(
            {
                f"on_{result}_script": (
                    f"tw.vars.set('current_{result}', True)" if representation == "current" else ""
                )
                for result in ("success", "failure")
            }
        )
    payload = {
        **entity_payload("OBJECT", "CONTROL"),
        "item_type": "SWITCH",
        "metadata_json": metadata,
    }
    created = await world.client.post(
        f"/api/adventures/{world.template_id}/editor/entity", json=payload
    )
    assert created.status_code == 200, created.text
    if representation == "flat":
        async with TestSessionLocal() as db:
            row = await db.scalar(
                select(WorldEntity).where(
                    WorldEntity.template_id == world.template_id, WorldEntity.id == "CONTROL"
                )
            )
            row.metadata_json = {key: value for key, value in metadata.items() if key != "switch"}
            flag_modified(row, "metadata_json")
            await db.commit()
    response = await world.client.get(f"/api/adventures/{world.template_id}/editor/assets")
    assert response.status_code == 200, response.text
    projected = next(row for row in response.json()["objects"] if row["id"] == "CONTROL")
    authoritative = metadata if representation == "flat" else config
    expected = {
        f"on_{result}_script": authoritative.get(f"on_{result}_script", "")
        for result in ("success", "failure")
    }
    assert {field: projected[field] for field in expected} == expected
    saved = await world.client.patch(
        f"/api/adventures/{world.template_id}/editor/entity",
        json={
            "target_type": "object",
            "target_id": "CONTROL",
            "name": "Renamed control",
            "switch_states": projected["switch_states"],
            "switch_initial_state": projected["switch_initial_state"],
            "switch_transitions": projected["switch_transitions"],
            **{field: projected[field] for field in expected},
        },
    )
    assert saved.status_code == 200, saved.text
    async with TestSessionLocal() as db:
        row = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.template_id == world.template_id, WorldEntity.id == "CONTROL"
            )
        )
        config = SwitchService.resolve_switch_config(row)
        assert {field: config.get(field, "") for field in expected} == expected
        context = GameContext(variables={})
        for success in (True, False):
            SwitchService.execute_transition_triggers(
                ScriptRunner(), config, None, success, context, "CONTROL"
            )
        suffix = "stale" if representation == "flat" else "current"
        assert context.changeset.var_updates == (
            {f"{suffix}_success": True, f"{suffix}_failure": True}
            if representation in {"flat", "current"}
            else {}
        )
