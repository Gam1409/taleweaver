"""State scope follows current visibility without granting possession authority."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.clothing.narration import narration_clothing
from backend.engine.physical_conditions.ledger import apply
from backend.engine.physical_conditions.scope import item_scope
from backend.engine.visual_novel.continuity import possession_snapshot
from tests.test_item_state_identity import record


def fixture(*, locked=False, hidden=False, scene="ROOM", private=False):
    item = {"id": "flask", "name": "Flask", "description": "An empty flask."}
    container = SimpleNamespace(
        id="BASIN",
        name="Basin",
        entity_type="OBJECT",
        item_type="CONTAINER",
        description="A fixed basin.",
        inventory=[item],
        is_portable=False,
        is_hidden=hidden,
        is_in_inventory=False,
        current_scene_id=scene,
        metadata_json={"locked": locked},
        session_id="SESSION",
    )
    states, _, errors = apply(
        {},
        [{**record(), "visibility": "private" if private else "public"}],
        targets={"flask"},
        item_targets={"flask"},
        narration="The flask is half full.",
        message_id="source",
        session_id="SESSION",
        minute=12,
    )
    assert not errors
    manager = SimpleNamespace(
        avatar=SimpleNamespace(name="Hero", inventory=[], equipment={}, visual_profile=None),
        state=SimpleNamespace(entity_states=states, session_id="SESSION", current_scene_id="ROOM"),
    )
    return manager, container


def test_narration_includes_current_public_state_of_accessible_container_contents():
    manager, container = fixture()
    before = deepcopy(manager.state.entity_states)
    snapshot = possession_snapshot(manager, [container])
    assert snapshot.owners["flask"] == "BASIN"
    _, prompt = narration_clothing(manager, [container], [container])
    assert "The flask is half full." in prompt
    assert manager.state.entity_states == before


@pytest.mark.parametrize(
    "options", [{"locked": True}, {"hidden": True}, {"scene": "ELSEWHERE"}, {"private": True}]
)
def test_unavailable_or_private_container_contents_do_not_enter_narration(options):
    manager, container = fixture(**options)
    visible = [] if options.get("hidden") or options.get("scene") else [container]
    _, prompt = narration_clothing(manager, visible, [container])
    assert "The flask is half full." not in prompt


def test_state_scope_does_not_change_transferability_or_duplicate_portable_items():
    manager, basin = fixture()
    snapshot = possession_snapshot(manager, [basin])
    before = deepcopy(snapshot)
    scope = item_scope(manager, [basin], snapshot=snapshot, visible=[basin])
    assert scope.item_ids == {"BASIN", "flask"}
    assert set(scope.additional_items) == {"BASIN"}
    assert "BASIN" not in snapshot.items and snapshot == before
    basin.is_portable = True
    scope = item_scope(manager, [basin], visible=[basin])
    assert not scope.additional_items


def test_shadow_world_row_does_not_expose_an_absent_npcs_possession():
    manager, basin = fixture()
    basin.inventory = []
    npc = SimpleNamespace(
        id="KEEPER",
        name="Keeper",
        entity_type="NPC",
        current_scene_id="ELSEWHERE",
        inventory=[{"id": "BASIN", "name": "Basin"}],
        metadata_json={},
        is_hidden=False,
        session_id="SESSION",
    )
    scope = item_scope(manager, [basin, npc], visible=[basin])
    assert "BASIN" not in scope.item_ids | scope.public_ids


@pytest.mark.asyncio
async def test_portable_only_reconciliation_keeps_its_existing_context_budget(monkeypatch):
    import json

    from backend.engine.narrated_items.runtime import reconcile_items
    from tests.test_item_reconciliation_blocks import reconciliation_fixture

    manager, provider = reconciliation_fixture(monkeypatch)
    await reconcile_items(manager, "The room is quiet.", completed=True, resolution="")
    provider.assert_awaited_once()
    payload = json.loads(provider.await_args.args[1])
    assert "item_state_targets" not in payload
