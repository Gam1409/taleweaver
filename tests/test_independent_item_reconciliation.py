"""A localized player denial preserves unrelated NPC item operations through their owner."""

from copy import deepcopy
from dataclasses import replace

import pytest

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items import independent_state
from backend.engine.narrated_items.repair_validation import _item_chain_conflict
from backend.engine.narrated_items.runtime import KEY, reconcile_items
from backend.engine.narrated_items.schema import ItemExtraction
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_extraction_repair_validation import check
from tests.test_narrated_items import action
from tests.test_npc_action_previews import fixture as owner_fixture
from tests.test_shared_scene_staging import ACTION, TEXT, SharedRoles, seed
from tests.test_vn_turn_integration import final_payload


class LocalDenialRoles(SharedRoles):
    denied = True

    async def structured(self, *args, **kwargs):
        result = await super().structured(*args, **kwargs)
        if type(result).__name__.startswith("VNProgressionIntent") and self.denied:
            result.removed_inventory_item_ids = ["NOT_OWNED"]
        return result


@pytest.mark.parametrize("blocked", [False, True])
@pytest.mark.parametrize("staging", [False, True])
async def test_unrelated_wardrobe_uses_real_owner_after_local_player_denial(
    monkeypatch, blocked, staging
):
    roles = LocalDenialRoles()
    roles.denied = blocked
    async with TestSessionLocal() as db:
        _roles, user, avatar, state = await seed(monkeypatch, db, enabled=staging, roles=roles)
        player_before = deepcopy(avatar.inventory), deepcopy(avatar.equipment)
        manager = GameTurnManager(db, state.session_id, user)
        events = [event async for event in manager.process_turn("Continue.")]
        assert final_payload(events)["status"] == "success", "".join(events)
        assert (avatar.inventory, avatar.equipment) == player_before
        assert state.entity_states["LINA"]["visual_profile"]["worn"] == []
        audit = state.entity_states[KEY]
        assert [row["item"]["id"] for row in audit["accepted"]] == ["COAT"]
        assert audit["status"] == ("needs_review" if blocked else "complete")
        assert (
            sum(call[0] in {"ItemExtraction", "SharedItemExtraction"} for call in roles.calls) == 1
        )
        assert not any("No additional inventory changes were applied" in event for event in events)
        calls = len(roles.calls)
        assert (
            await reconcile_items(
                manager,
                TEXT,
                completed=True,
                resolution="Denied.",
                blocked=blocked,
                blocked_targets={"__player__"} if blocked else None,
            )
            == []
        )
        assert len(roles.calls) == calls


async def test_mixed_blocked_player_prefix_retains_original_npc_action_index(monkeypatch):
    roles = LocalDenialRoles()
    roles.actions = [
        {
            **ACTION,
            "item_id": "NOT_OWNED",
            "source_owner": "__player__",
            "destination_owner": "__player__",
        },
        ACTION,
    ]
    async with TestSessionLocal() as db:
        _roles, user, avatar, state = await seed(monkeypatch, db, roles=roles)
        before = deepcopy(avatar.inventory)
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        assert avatar.inventory == before
        assert state.entity_states["LINA"]["visual_profile"]["worn"] == []
        assert [row["action_index"] for row in state.entity_states[KEY]["accepted"]] == [1]


@pytest.mark.parametrize(
    "changes,denied",
    [
        ({"destination_owner": "__player__"}, {"__player__"}),
        ({"source_owner": "__player__"}, {"__player__"}),
        ({"source_owner": "__scene__"}, {"__player__"}),
        ({"item_id": "PLAYER_COAT"}, {"__player__"}),
        (
            {"item_id": "OTHER_COAT", "source_owner": "other", "destination_owner": "other"},
            {"other"},
        ),
        ({"item_id": "COAT"}, {"COAT"}),
        ({"source_owner": "Unknown"}, {"__player__"}),
    ],
)
def test_independent_item_selector_cannot_cross_blocked_owners_or_items(changes, denied):
    _manager, scope, _draft = owner_fixture()
    extraction = ItemExtraction(
        actions=[{**ACTION, "source_owner": "npc", "destination_owner": "npc", **changes}]
    )
    before = deepcopy(scope.actors), deepcopy(scope.possessions)
    retained, indices, failures = independent_state.items(
        extraction, scope.actors, scope.possessions, denied, (3,)
    )
    assert not retained.actions and not indices
    assert [failure.action_index for failure in failures] == [3]
    assert (scope.actors, scope.possessions) == before


def test_a_blocked_step_rejects_its_whole_item_chain_without_reindexing_other_items():
    _manager, scope, _draft = owner_fixture()
    extraction = ItemExtraction(
        actions=[
            {**ACTION, "source_owner": "npc", "destination_owner": "npc"},
            {**ACTION, "source_owner": "npc", "destination_owner": "__player__"},
            {**ACTION, "item_id": "FLASK", "source_owner": "npc", "destination_owner": "npc"},
        ]
    )
    retained, indices, failures = independent_state.items(
        extraction, scope.actors, scope.possessions, {"__player__"}, (0, 2, 4)
    )
    assert [action.item_id for action in retained.actions] == ["FLASK"]
    assert indices == (4,)
    assert {failure.action_index for failure in failures} == {0, 2}


def test_filtered_prefix_preserves_original_vs_correction_chain_identity():
    extraction = ItemExtraction(actions=[ACTION, ACTION])
    assert _item_chain_conflict(extraction, 2, (1, 3))
    assert not _item_chain_conflict(extraction, 4, (1, 3))


async def test_stale_item_source_cannot_change_an_unblocked_npc_garment(monkeypatch):
    roles = LocalDenialRoles()
    roles.actions = [{**ACTION, "evidence": "A quotation from another scene."}]
    async with TestSessionLocal() as db:
        _roles, user, _avatar, state = await seed(monkeypatch, db, roles=roles)
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        assert state.entity_states["LINA"]["visual_profile"]["worn"]
        assert not state.entity_states[KEY]["accepted"]


@pytest.mark.parametrize("destination,allowed", [("NPC", True), ("__player__", False)])
async def test_existing_correction_preview_uses_the_same_independent_item_scope(
    destination, allowed
):
    validator, original, refs = check("Anna takes off her own shirt.", blocked={"__player__"})
    validator = replace(validator, item_changes_allowed=False)
    candidate = original.model_copy(deep=True)
    candidate.coverage = {"c0": ["items"]}
    candidate.actions = [action(destination_owner=destination, evidence=refs[0]).model_dump()]
    before = deepcopy(validator.actors), deepcopy(validator.manager.state.entity_states)
    assert await validator(candidate, original) is allowed
    assert (validator.actors, validator.manager.state.entity_states) == before


async def test_independent_selector_does_not_materialize_new_items():
    _manager, scope, _draft = owner_fixture()
    extraction = ItemExtraction(
        actions=[
            {
                "new_item": {
                    "name": "New scarf",
                    "description": "A wool scarf.",
                    "kind": "ordinary",
                },
                "source_owner": "npc",
                "destination_owner": "npc",
                "disposition": "carried",
                "basis": "completed",
                "evidence": "NPC produces a new scarf.",
            },
            {**ACTION, "source_owner": "npc", "destination_owner": "npc"},
        ]
    )
    retained, indices, failures = independent_state.items(
        extraction, scope.actors, scope.possessions, {"__player__"}, (0, 4)
    )
    assert indices == (4,) and retained.actions[0].item_id == "COAT"
    assert [failure.action_index for failure in failures] == [0]


@pytest.mark.parametrize("targets", [None, set(), {"LINA", "COAT"}])
async def test_unscoped_or_related_denial_never_admits_the_npc_item(monkeypatch, targets):
    async with TestSessionLocal() as db:
        _roles, user, _avatar, state = await seed(monkeypatch, db)
        manager = GameTurnManager(db, state.session_id, user)
        assert await manager.initialize()
        message = ChatMessage(
            session_id=state.session_id, scene_id="START", role="user", content="Continue."
        )
        db.add(message)
        await db.flush()
        manager._vn_player_message_id = message.id
        await reconcile_items(
            manager,
            TEXT,
            completed=True,
            resolution="Denied.",
            blocked=True,
            blocked_reason="The preliminary action was rejected.",
            blocked_targets=targets,
        )
        assert not state.entity_states[KEY]["accepted"]
