"""Ordered pose previews use planned custody without changing canonical observations."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.chpm.observable_state import project
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.visuals import session_objects
from backend.engine.npc_actions.contracts import (
    Approach,
    Discard,
    Give,
    PutDown,
    Take,
    TakeOff,
)
from backend.engine.npc_actions.preparation import capture
from backend.engine.npc_actions.preview import Draft
from backend.engine.npc_actions.publication import publish
from backend.engine.npc_actions.settings import configure
from backend.engine.scene_staging.shared import _cast
from backend.engine.scene_staging.state import KEY
from backend.engine.visual_novel.continuity import SCENE, possession_snapshot
from backend.models.avatar import Avatar
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.observable_state_support import observation, world
from tests.test_npc_action_previews import fixture
from tests.test_npc_action_publication import fixture as stored_fixture


def staged_fixture():
    host, scope, _ = fixture()
    _, rows = world()
    view = project(host, rows, "npc", observation())
    scoped = replace(
        scope,
        player_id=host.avatar.id,
        cast=tuple(_cast(host, actor_records(host, rows), rows)),
        scene_objects={
            identifier: row["name"][:120]
            for identifier, row in view.entities.items()
            if row["kind"] == "item" and row.get("owner_id") == SCENE
        },
        staging_enabled=True,
    )
    return host, rows, Draft(scoped)


def test_put_down_then_approach_uses_the_same_newly_loose_item_without_publication():
    host, rows, draft = staged_fixture()
    canonical = deepcopy(draft.scope), deepcopy(host.state.entity_states)
    assert draft.execute(PutDown(tool="put_down_item", item_id="FLASK"))["status"] == "staged"
    result = draft.execute(Approach(tool="approach", target_id="FLASK"))
    assert result["status"] == "staged" and result["world_changed"] is False
    assert result["effect"]["placement"]["target"] == "FLASK"
    assert draft._possessions.owners["FLASK"] == SCENE
    assert (draft.scope, host.state.entity_states) == canonical
    assert project(host, rows, "npc", observation()).entities["FLASK"]["owner_id"] == "npc"


@pytest.mark.parametrize("give", [False, True])
def test_acquired_or_given_item_is_no_longer_a_loose_pose_target(give):
    _, _, draft = staged_fixture()
    assert draft.execute(Take(tool="take_item", item_id="KEY"))["status"] == "staged"
    if give:
        assert (
            draft.execute(Give(tool="give_item", item_id="KEY", recipient_id="other"))["status"]
            == "staged"
        )
    before = deepcopy(draft.working_copy())
    assert draft.execute(Approach(tool="approach", target_id="KEY"))["status"] == "blocked"
    assert draft.working_copy() == before
    assert len(draft.requests) == 1 + int(give)


def test_unrelated_custody_changes_preserve_fixed_visible_scene_targets():
    _, _, draft = staged_fixture()
    assert "BELL" in draft.scope.scene_objects and "BELL" not in draft._possessions.items
    assert draft.execute(Take(tool="take_item", item_id="KEY"))["status"] == "staged"
    assert draft.execute(PutDown(tool="put_down_item", item_id="FLASK"))["status"] == "staged"
    result = draft.execute(Approach(tool="approach", target_id="BELL"))
    assert result["status"] == "staged"
    assert result["effect"]["placement"]["target"] == "BELL"


def test_discard_restores_the_initial_target_projection_without_leaking_custody_or_pose():
    host, _, draft = staged_fixture()
    canonical = deepcopy(draft.scope), deepcopy(host.state.entity_states)
    assert draft.execute(Take(tool="take_item", item_id="KEY"))["status"] == "staged"
    assert draft.execute(PutDown(tool="put_down_item", item_id="FLASK"))["status"] == "staged"
    assert draft.execute(Approach(tool="approach", target_id="FLASK"))["status"] == "staged"
    assert draft.execute(Discard(tool="discard_actions"))["status"] == "discarded"
    assert draft.working_copy() == (
        draft.scope.actors,
        draft.scope.possessions,
        draft.scope.states,
    )
    assert draft.execute(Approach(tool="approach", target_id="FLASK"))["status"] == "blocked"
    assert draft.execute(Approach(tool="approach", target_id="KEY"))["status"] == "staged"
    assert (draft.scope, host.state.entity_states) == canonical


@pytest.mark.parametrize("target", ["HIDDEN", "AWAY", "OTHER_BAG_SECRET", "PLAYER_BAG_SECRET"])
def test_working_copy_cannot_add_inaccessible_targets(target):
    _, _, draft = staged_fixture()
    assert draft.execute(PutDown(tool="put_down_item", item_id="FLASK"))["status"] == "staged"
    assert (
        draft.execute(Approach(tool="approach", target_id=target))["status"] == "unavailable_entity"
    )
    assert [request.tool for request in draft.requests] == ["put_down_item"]


def test_a_worn_garment_becomes_a_scene_target_only_after_supported_removal_and_put_down():
    _, _, draft = staged_fixture()
    assert draft.execute(PutDown(tool="put_down_item", item_id="COAT"))["status"] == "blocked"
    assert draft.execute(Approach(tool="approach", target_id="COAT"))["status"] == "blocked"
    assert draft.execute(TakeOff(tool="take_off_item", item_id="COAT"))["status"] == "staged"
    assert draft.execute(PutDown(tool="put_down_item", item_id="COAT"))["status"] == "staged"
    assert draft.execute(Approach(tool="approach", target_id="COAT"))["status"] == "staged"


@pytest.mark.parametrize("item_id", ["HIDDEN_RING", "KEY"])
async def test_item_and_approach_plans_publish_and_reload_through_the_same_canonical_owners(
    item_id,
):
    async with TestSessionLocal() as db:
        host, observed, _ = await stored_fixture(db)
        host.state.entity_states = configure(host.state.entity_states, enabled=True)
        views = await capture_views(host, ["LINA"], observed)
        draft = (await capture(host, views, observed))["LINA"]
        if item_id == "KEY":
            assert draft.execute(Take(tool="take_item", item_id=item_id))["status"] == "staged"
            assert (
                draft.execute(Approach(tool="approach", target_id=item_id))["status"] == "blocked"
            )
        assert draft.execute(PutDown(tool="put_down_item", item_id=item_id))["status"] == "staged"
        assert draft.execute(Approach(tool="approach", target_id=item_id))["status"] == "staged"
        draft.approved = True
        outcomes = await publish(host, draft)
        assert [row["status"] for row in outcomes] == ["applied"] * len(draft.requests)
        assert await publish(host, draft) == outcomes
        await db.commit()
        state_id, avatar_id, game_id = host.state.id, host.avatar.id, host.game_id
    async with TestSessionLocal() as db:
        state = await db.get(SessionState, state_id)
        avatar = await db.get(Avatar, avatar_id)
        fresh = SimpleNamespace(state=state, avatar=avatar, game_id=game_id)
        current = possession_snapshot(fresh, await session_objects(db, game_id))
        assert current.owners[item_id] == SCENE
        placement = state.entity_states[KEY]["actors"]["LINA"]["placement"]
        assert placement["target_id"] == item_id
        assert placement["source_kind"] == "command"
        assert placement["command_operation"] == "approach"
        assert placement["source_message_id"] == observed.message_id
        assert placement["source_revision_id"] == observed.revision_id
