"""Local action tools reach canonical state without manufacturing recipient outcomes."""

from copy import deepcopy

import pytest

from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.chpm.observable_state import project
from backend.engine.chpm.state import KEY, load
from backend.engine.clothing.visuals import session_objects
from backend.engine.npc_actions import runtime as action_runtime
from backend.engine.npc_actions.contracts import Approach, Interact, Pose, Take
from backend.engine.npc_actions.preparation import capture
from backend.engine.npc_actions.publication import publish
from backend.engine.npc_actions.settings import configure
from backend.engine.physical_conditions.ledger import read
from backend.engine.scene_staging.state import KEY as STAGING_KEY
from tests.conftest import TestSessionLocal
from tests.test_chpm_action_turn import ActionRoles
from tests.test_chpm_host_turn import run
from tests.test_chpm_notebook_turn import ACTION, install
from tests.test_chpm_observable_turn import DETAIL, prepare
from tests.test_npc_action_publication import fixture


class LocalActionRoles(ActionRoles):
    @staticmethod
    def commands():
        return [
            {"name": "set_pose", "arguments": {"posture": "on_all_fours"}},
            {"name": "approach", "arguments": {"target_id": "@player", "mode": "crawl"}},
        ]


class InteractionRoles(ActionRoles):
    @staticmethod
    def commands():
        return [
            {
                "name": "interact",
                "arguments": {"target_id": "@player", "action": "Offer my hand to the visitor."},
            }
        ]


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("roles_type", [LocalActionRoles, InteractionRoles])
async def test_local_actions_survive_both_ports_and_do_not_control_player(
    monkeypatch, protocol, roles_type
):
    roles = roles_type()
    install(monkeypatch, roles)
    published = {}
    original = action_runtime.publish_turn

    async def record_publication(manager, turn):
        await original(manager, turn)
        published.update(deepcopy(turn.action_outcomes))

    monkeypatch.setattr(action_runtime, "publish_turn", record_publication)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", protocol, False)
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = configure(
            {**state.entity_states, KEY: kernel.model_dump()}, enabled=True
        )
        await db.commit()
        manager, chunks = await run(db, user, ACTION)
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        assert not any(chunk.startswith("event: error") for chunk in chunks)
        await db.refresh(state)
        outcomes = published["LINA"]
        assert [row["status"] for row in outcomes] == (
            ["applied", "applied"] if roles_type is LocalActionRoles else ["attempted"]
        )
        decision = load(state).actors["LINA"]
        view = project(
            manager, await session_objects(db, manager.game_id), "LINA", decision.observation
        )
        if roles_type is LocalActionRoles:
            assert view.entities["LINA"]["posture"] == "on_all_fours"
            assert view.entities["LINA"]["placement"] == {
                "relation": "near",
                "target_kind": "character",
                "target": "@player",
            }
            proof = state.entity_states[STAGING_KEY]["actors"]["LINA"]["posture"]
            assert proof["source_kind"] == "command"
            assert proof["source_message_id"] == manager._vn_player_message_id
            assert "evidence" not in proof
        else:
            assert outcomes[0]["effect"]["consequences"].startswith("unresolved")
            assert "posture" not in view.entities["@player"]
            assert not state.entity_states.get(STAGING_KEY, {}).get("explicit")
        assert any(row.detail == DETAIL for row in read(state.entity_states).conditions.values())
        assert "authoritative_command_outcomes" in str(roles.prompts)
        assert load(state).usage.calls == 4


async def test_an_approach_target_taken_by_another_actor_is_rechecked_before_publication():
    async with TestSessionLocal() as db:
        host, observed, _ = await fixture(db)
        host.state.entity_states = configure(host.state.entity_states, enabled=True)
        views = await capture_views(host, ["LINA", "SECOND"], observed)
        drafts = await capture(host, views, observed)
        approaching, taking = drafts["LINA"], drafts["SECOND"]
        assert approaching.execute(Approach(tool="approach", target_id="KEY"))["status"] == "staged"
        assert taking.execute(Take(tool="take_item", item_id="KEY"))["status"] == "staged"
        approaching.approved = taking.approved = True
        assert (await publish(host, taking))[0]["status"] == "applied"
        before = deepcopy(host.state.entity_states)
        assert (await publish(host, approaching))[0]["status"] == "blocked"
        assert host.state.entity_states == before


async def test_pose_receipt_includes_placement_only_when_the_owner_clears_it():
    async with TestSessionLocal() as db:
        host, observed, _ = await fixture(db)
        host.state.entity_states = configure(host.state.entity_states, enabled=True)
        views = await capture_views(host, ["LINA"], observed)
        draft = (await capture(host, views, observed))["LINA"]
        assert draft.execute(Approach(tool="approach", target_id="@player"))["status"] == "staged"
        same = draft.execute(Pose(tool="set_pose", posture="standing"))
        assert "placement" not in same["effect"]
        changed = draft.execute(Pose(tool="set_pose", posture="sitting"))
        assert "placement" in changed["effect"] and changed["effect"]["placement"] is None
        draft.approved = True
        assert [row["status"] for row in await publish(host, draft)] == ["applied"] * 3
        assert "placement" not in host.state.entity_states[STAGING_KEY]["actors"]["LINA"]


async def test_interaction_preview_never_claims_actual_player_compliance():
    async with TestSessionLocal() as db:
        host, _, drafts = await fixture(db)
        before = deepcopy(host.state.entity_states), deepcopy(host.avatar.inventory)
        draft = drafts["LINA"]
        result = draft.execute(
            Interact(tool="interact", target_id="@player", action="Offer my hand to the visitor.")
        )
        assert result["status"] == "staged" and result["world_changed"] is False
        draft.approved = True
        assert (await publish(host, draft))[0]["status"] == "attempted"
        assert (host.state.entity_states, host.avatar.inventory) == before
