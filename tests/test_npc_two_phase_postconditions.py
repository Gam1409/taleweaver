"""Verify real owner writes before acknowledging each selected NPC operation."""

from copy import deepcopy

import pytest

from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.visuals import session_objects
from backend.engine.npc_actions import publication
from backend.engine.npc_actions.contracts import (
    Adjust,
    Approach,
    Give,
    Pose,
    PutDown,
    Take,
    TakeOff,
    Wear,
)
from backend.engine.npc_actions.preparation import capture
from backend.engine.scene_staging.state import KEY as STAGING_KEY
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.engine.visual_novel.continuity import SCENE, possession_snapshot
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_npc_action_publication import fixture


def approve(draft, *requests):
    for req in requests:
        assert draft.execute(req)["status"] == "staged"
    draft.approved = True


async def owners(host):
    return possession_snapshot(host, await session_objects(host.db, host.game_id)).owners


async def garment_fixture(db):
    host, observed, _ = await fixture(db)
    db.add(
        WorldEntity(
            id="COAT",
            session_id=host.game_id,
            entity_type="OBJECT",
            current_scene_id="START",
            name="Blue coat",
            description="An outdoor coat.",
            is_portable=True,
            metadata_json={"clothing": {"layer": 2, "coverage": ["torso", "arms"]}},
        )
    )
    write_settings(host.state, VnSettings(scene_staging=True))
    host.state.entity_states = {
        **host.state.entity_states,
        "LINA": {"visual_profile": {"version": 1, "worn": []}},
    }
    await db.commit()
    views = await capture_views(host, ["LINA"], observed)
    return host, (await capture(host, views, observed))["LINA"]


async def test_chain_verified_on_each_owning_step_contested_item_and_fresh_reload():
    async with TestSessionLocal() as db:
        host, _, drafts = await fixture(db)
        first, second = drafts["LINA"], drafts["SECOND"]
        approve(
            first,
            Take(tool="take_item", item_id="KEY"),
            Give(tool="give_item", item_id="KEY", recipient_id="@player"),
        )
        approve(
            second,
            Take(tool="take_item", item_id="KEY"),
            PutDown(tool="put_down_item", item_id="KEY"),
        )
        results = await publication.publish(host, first, verify_postconditions=True)
        assert [row["status"] for row in results] == ["applied", "applied"]
        assert await publication.publish(host, first, verify_postconditions=True) == results
        denied = await publication.publish(host, second, verify_postconditions=True)
        assert [row["status"] for row in denied] == ["blocked", "skipped_dependency"]
        await db.commit()
        db.expire_all()
        await db.refresh(host.state)
        await db.refresh(host.avatar)
        assert (await owners(host))["KEY"] == "__player__"


def approve_wardrobe_and_pose(draft):
    approve(
        draft,
        Take(tool="take_item", item_id="COAT"),
        Wear(tool="wear_item", item_id="COAT"),
        Adjust(tool="adjust_clothing", item_id="COAT", uncovered_regions=["arms"]),
        TakeOff(tool="take_off_item", item_id="COAT"),
        PutDown(tool="put_down_item", item_id="COAT", position="on the bench"),
        Approach(tool="approach", target_id="COAT", mode="crawl"),
        Pose(tool="set_pose", posture="standing"),
    )


async def test_wear_adjust_remove_drop_and_posture_use_real_owner_views_in_order():
    async with TestSessionLocal() as db:
        host, draft = await garment_fixture(db)
        approve_wardrobe_and_pose(draft)
        results = await publication.publish(host, draft, verify_postconditions=True)
        assert [row["status"] for row in results] == ["applied"] * 7
        await db.commit()
        await db.refresh(host.state)
        rows = await session_objects(db, host.game_id, refresh=True)
        snap = possession_snapshot(host, rows)
        assert (
            snap.owners["COAT"] == SCENE
            and snap.items["COAT"]["spatial_position"] == "on the bench"
        )
        profile = load_profile(actor_records(host, rows)["LINA"]["visual_profile"])
        assert profile is not None and all(item.item_id != "COAT" for item in profile.worn)
        pose = host.state.entity_states[STAGING_KEY]["actors"]["LINA"]
        assert pose["posture"]["value"] == "standing" and "placement" not in pose


@pytest.mark.parametrize(
    ("tool", "field"),
    [("adjust_clothing", "coverage"), ("put_down_item", "placement"), ("approach", "placement")],
)
async def test_effects_match_real_coverage_position_and_prop_id(monkeypatch, tool, field):
    from backend.engine.npc_actions import postconditions

    async with TestSessionLocal() as db:
        host, draft = await garment_fixture(db)
        approve_wardrobe_and_pose(draft)
        apply = publication._apply
        diagnostics = []

        async def corrupt_one_field(manager, scope, request, preview):
            await apply(manager, scope, request, preview)
            if request.tool != tool:
                return
            states = deepcopy(manager.state.entity_states)
            if tool == "adjust_clothing":
                states["LINA"]["visual_profile"]["worn"][0]["uncovered_regions"] = []
            elif tool == "put_down_item":
                states["COAT"]["spatial_position"] = "beside the bench"
            else:
                # The display label and command stamp still agree.
                states[STAGING_KEY]["actors"]["LINA"]["placement"]["target_id"] = "KEY"
            manager.state.entity_states = states

        monkeypatch.setattr(publication, "_apply", corrupt_one_field)
        monkeypatch.setattr(postconditions, "reject", lambda *args, **kw: diagnostics.append(kw))
        with pytest.raises(postconditions.PostconditionViolationError):
            async with db.begin_nested():
                await publication.publish(host, draft, verify_postconditions=True)
        assert [(row["tool"], row["field"]) for row in diagnostics] == [(tool, field)]
        assert draft.published_results is None


async def test_false_success_rolls_back_the_verified_prefix_and_hides_private_values(monkeypatch):
    from backend.engine.npc_actions import postconditions

    async with TestSessionLocal() as db:
        host, _, drafts = await fixture(db)
        draft = drafts["LINA"]
        approve(
            draft,
            Take(tool="take_item", item_id="KEY"),
            Give(tool="give_item", item_id="KEY", recipient_id="SECOND"),
        )
        apply = publication._apply
        diagnostics = []

        async def drop_last(host, scope, request, preview):
            if request.tool != "give_item":
                await apply(host, scope, request, preview)

        monkeypatch.setattr(publication, "_apply", drop_last)
        monkeypatch.setattr(
            postconditions, "reject", lambda *args, **kw: diagnostics.append((args, kw))
        )
        with pytest.raises(postconditions.PostconditionViolationError):
            async with db.begin_nested():
                await publication.publish(host, draft, verify_postconditions=True)
        await db.refresh(host.state)
        assert (await owners(host))["KEY"] == SCENE and draft.published_results is None
        [(args, details)] = diagnostics
        assert args[:2] == ("npc_actions", "postcondition_violation")
        assert details["operation_id"] == draft.operations[1].operation_id
        assert "SECOND" not in str((args, details)) and "KEY" not in str((args, details))


async def test_recipient_precedence_cannot_hide_duplicate_custody(monkeypatch):
    from backend.engine.npc_actions import postconditions

    async with TestSessionLocal() as db:
        host, _, drafts = await fixture(db)
        draft = drafts["LINA"]
        approve(
            draft,
            Take(tool="take_item", item_id="KEY"),
            Give(tool="give_item", item_id="KEY", recipient_id="@player"),
        )
        apply = publication._apply

        async def copy_instead_of_give(manager, scope, request, preview):
            await apply(manager, scope, request, preview)
            if request.tool == "give_item":
                states = deepcopy(manager.state.entity_states)
                states["LINA"]["inventory"].append({"id": "KEY", "name": "A key"})
                manager.state.entity_states = states

        monkeypatch.setattr(publication, "_apply", copy_instead_of_give)
        with pytest.raises(postconditions.PostconditionViolationError):
            async with db.begin_nested():
                await publication.publish(host, draft, verify_postconditions=True)
        await db.refresh(host.state)
        await db.refresh(host.avatar)
        assert (await owners(host))["KEY"] == SCENE


async def test_verification_cannot_complete_an_invalidated_input_across_its_read(monkeypatch):
    from backend.engine import turn_controls
    from backend.engine.npc_actions import postconditions

    async with TestSessionLocal() as db:
        host, _, drafts = await fixture(db)
        draft = drafts["LINA"]
        approve(draft, Take(tool="take_item", item_id="KEY"))

        async def invalidate(db, session_id):
            rows = await session_objects(db, session_id)
            turn_controls.close(host)
            return rows

        monkeypatch.setattr(postconditions, "session_objects", invalidate)
        with pytest.raises(turn_controls.ControlBindingError):
            async with db.begin_nested():
                await publication.publish(host, draft, verify_postconditions=True)
        await db.refresh(host.state)
        assert (await owners(host))["KEY"] == SCENE
        assert draft.published_results is None


@pytest.mark.parametrize("mode", ["legacy", "two_phase"])
async def test_runtime_enables_postconditions_only_for_experimental_mode(monkeypatch, mode):
    from backend.engine.chpm.state import KEY
    from backend.engine.npc_actions import postconditions, runtime
    from tests.test_npc_action_lifecycle import controller_turn

    async with TestSessionLocal() as db:
        host, observed, drafts = await fixture(db)
        draft = drafts["LINA"]
        approve(draft, Take(tool="take_item", item_id="KEY"))
        turn = controller_turn(host, observed, draft)
        turn.initial.settings.npc_decision_mode = mode
        host.state.entity_states = {**host.state.entity_states, KEY: turn.initial.model_dump()}

        async def skip_write(*args):
            pass

        monkeypatch.setattr(publication, "_apply", skip_write)
        if mode == "legacy":
            await runtime.publish_turn(host, turn)
            assert turn.action_outcomes["LINA"][0]["status"] == "applied"
        else:
            with pytest.raises(postconditions.PostconditionViolationError):
                await runtime.publish_turn(host, turn)
            assert not turn.action_outcomes and draft.published_results is None
