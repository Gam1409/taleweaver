"""A proven acquisition permits a handoff without declaring the whole wardrobe known."""

from dataclasses import replace
from hashlib import sha256

import pytest

from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.chpm.observable_state import project
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.visuals import session_objects
from backend.engine.npc_actions.contracts import Discard, Give, PutDown, Take, Wear
from backend.engine.npc_actions.preparation import capture
from backend.engine.npc_actions.preview import Draft
from backend.engine.npc_actions.publication import publish
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.observable_state_support import garment, observation, world
from tests.test_npc_action_previews import fixture as preview_fixture
from tests.test_npc_action_publication import fixture as publication_fixture


def preview():
    host, rows = world()
    next(row for row in rows if row.id == "npc").visual_profile = None
    rows.append(garment("LOOSE_COAT"))
    _, scope, _ = preview_fixture()
    return Draft(
        replace(
            scope,
            actors=actor_records(host, rows),
            possessions=possession_snapshot(host, rows),
            accessible_ids=frozenset(project(host, rows, "npc", observation()).entities),
            input_hash=sha256(b"I wait.").hexdigest(),
        )
    )


@pytest.mark.parametrize(
    "handoff",
    [
        Give(tool="give_item", item_id="LOOSE_COAT", recipient_id="other"),
        PutDown(tool="put_down_item", item_id="LOOSE_COAT"),
    ],
)
def test_newly_acquired_garment_is_proven_carried_without_a_global_wardrobe(handoff):
    draft = preview()
    assert draft.execute(Take(tool="take_item", item_id="LOOSE_COAT"))["status"] == "staged"
    assert draft.execute(handoff)["status"] == "staged"
    assert draft.working_copy()[0]["npc"]["visual_profile"] is None
    assert draft.scope.actors["npc"]["visual_profile"] is None


def test_discard_removes_acquisition_proof_and_does_not_authorize_unknown_existing_wear():
    draft = preview()
    assert draft.execute(Take(tool="take_item", item_id="LOOSE_COAT"))["status"] == "staged"
    assert draft.execute(Discard(tool="discard_actions"))["status"] == "discarded"
    assert draft.execute(PutDown(tool="put_down_item", item_id="LOOSE_COAT"))["status"] == "blocked"
    result = draft.execute(Give(tool="give_item", item_id="COAT", recipient_id="other"))
    assert result["status"] == "blocked" and "unknown" in result["message"]
    assert draft.execute(Take(tool="take_item", item_id="LOOSE_COAT"))["status"] == "staged"
    assert draft.execute(PutDown(tool="put_down_item", item_id="LOOSE_COAT"))["status"] == "staged"


def test_later_confirmed_wear_overrides_an_earlier_acquisition_receipt():
    draft = preview()
    assert draft.execute(Take(tool="take_item", item_id="LOOSE_COAT"))["status"] == "staged"
    assert draft.execute(Wear(tool="wear_item", item_id="LOOSE_COAT"))["status"] == "staged"
    result = draft.execute(Give(tool="give_item", item_id="LOOSE_COAT", recipient_id="other"))
    assert result["status"] == "blocked" and "worn" in result["message"]


async def stored_fixture(db):
    host, observed, _ = await publication_fixture(db)
    host.state.entity_states = {
        **host.state.entity_states,
        "LINA": {**host.state.entity_states.get("LINA", {}), "visual_profile": None},
    }
    db.add(
        WorldEntity(
            id="LOOSE_COAT",
            session_id=host.game_id,
            entity_type="OBJECT",
            name="A loose coat",
            description="A loose coat on the bench.",
            current_scene_id="START",
            is_hidden=False,
            is_in_inventory=False,
            is_portable=True,
            metadata_json={"clothing": {"layer": 2, "coverage": ["torso", "arms"]}},
        )
    )
    await db.commit()
    views = await capture_views(host, ["LINA", "SECOND"], observed)
    return host, await capture(host, views, observed)


@pytest.mark.parametrize("destination", ["SECOND", "__scene__"])
async def test_actual_publication_reuses_only_successful_carried_command_receipts(destination):
    async with TestSessionLocal() as db:
        host, drafts = await stored_fixture(db)
        draft = drafts["LINA"]
        assert draft.execute(Take(tool="take_item", item_id="LOOSE_COAT"))["status"] == "staged"
        request = (
            PutDown(tool="put_down_item", item_id="LOOSE_COAT")
            if destination == "__scene__"
            else Give(tool="give_item", item_id="LOOSE_COAT", recipient_id=destination)
        )
        assert draft.execute(request)["status"] == "staged"
        draft.approved = True
        assert [row["status"] for row in await publish(host, draft)] == ["applied", "applied"]
        await db.commit()
        snapshot = possession_snapshot(host, await session_objects(db, host.game_id))
        assert snapshot.owners["LOOSE_COAT"] == destination
        assert host.state.entity_states["LINA"]["visual_profile"] is None


async def test_competing_acquisition_cannot_be_overridden_by_a_staged_carried_receipt():
    async with TestSessionLocal() as db:
        host, drafts = await stored_fixture(db)
        draft, competitor = drafts["LINA"], drafts["SECOND"]
        for plan in (draft, competitor):
            assert plan.execute(Take(tool="take_item", item_id="LOOSE_COAT"))["status"] == "staged"
            plan.approved = True
        draft.approved = False
        assert (
            draft.execute(Give(tool="give_item", item_id="LOOSE_COAT", recipient_id="SECOND"))[
                "status"
            ]
            == "staged"
        )
        draft.approved = True
        assert (await publish(host, competitor))[0]["status"] == "applied"
        assert [row["status"] for row in await publish(host, draft)] == [
            "blocked",
            "skipped_dependency",
        ]
