"""Public receipts and reviews use one player alias while owners keep canonical IDs."""

from copy import deepcopy

import pytest

from backend.engine import turn_controls
from backend.engine.chpm import rendering, runtime
from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.clothing.visuals import session_objects
from backend.engine.npc_actions import execution_frame, outcome_projection
from backend.engine.npc_actions.contracts import Approach, Give, Take
from backend.engine.npc_actions.preparation import capture
from backend.engine.npc_actions.publication import publish
from backend.engine.npc_actions.settings import configure
from backend.engine.scene_staging.state import KEY as STAGING_KEY
from backend.engine.visual_novel.continuity import PLAYER, possession_snapshot
from tests.conftest import TestSessionLocal
from tests.test_npc_completed_change_review import reviewer
from tests.test_npc_execution_frame import prepared

TEXT = 'Lina: "I will stand beside you."\nLina approaches the visitor.'


async def published(db, requests):
    manager, observed, _, turn = await prepared(db)
    manager.state.entity_states = configure(manager.state.entity_states, enabled=True)
    views = await capture_views(manager, ["LINA"], observed)
    draft = (await capture(manager, views, observed))["LINA"]
    turn.action_drafts = {"LINA": draft}
    for request in requests:
        assert draft.execute(request)["status"] == "staged"
    draft.approved = True
    turn.action_outcomes = {"LINA": await publish(manager, draft, verify_postconditions=True)}
    assert all(row["status"] == "applied" for row in turn.action_outcomes["LINA"])
    turn.control = turn_controls.scope(manager, "narration_review", observation=observed)
    turn.initial.settings.max_input_chars = 64000
    turn.initial.settings.mode = "live"
    turn.present_names = {"LINA": "Lina", "SECOND": "Second observer"}
    await execution_frame.capture(manager, turn, observed)
    return manager, turn


def claim(turn, *, target_id="@player", recipient_id=None):
    row = runtime.contract_data(turn)["LINA"]["authoritative_command_outcomes"][-1]
    return {
        "actor_id": "LINA",
        "passage_id": "p1",
        "operation_id": row["operation_id"],
        "tool": row["tool"],
        "target_id": target_id,
        "recipient_id": recipient_id,
        "posture": "standing" if row["tool"] == "approach" else None,
    }


async def test_real_approach_publication_and_review_share_the_public_player_id(monkeypatch):
    async with TestSessionLocal() as db:
        manager, turn = await published(db, [Approach(tool="approach", target_id="@player")])
        canonical = deepcopy(turn.action_outcomes)
        internal = manager.state.entity_states[STAGING_KEY]["actors"]["LINA"]["placement"]
        assert internal["target"] == manager.avatar.id != "@player"
        contract = runtime.contract_data(turn)
        row = contract["LINA"]["authoritative_command_outcomes"][0]
        assert row["effect"]["placement"]["target"] == "@player"
        assert (
            contract["current_execution_frame"]["entities"]["LINA"]["placement"]
            == row["effect"]["placement"]
        )
        seen = reviewer(monkeypatch, [claim(turn)])
        assert (await rendering._review(manager, turn, TEXT, "")).matches
        assert seen[0]["contract"] == contract
        assert turn.action_outcomes == canonical
        assert canonical["LINA"][0]["effect"]["placement"]["target"] == manager.avatar.id


@pytest.mark.parametrize("target", ["SECOND", "canonical_player_id"])
async def test_approach_review_cannot_match_a_different_or_nonpublic_id(monkeypatch, target):
    async with TestSessionLocal() as db:
        manager, turn = await published(db, [Approach(tool="approach", target_id="@player")])
        target = manager.avatar.id if target == "canonical_player_id" else target
        reviewer(monkeypatch, [claim(turn, target_id=target)])
        assert not (await rendering._review(manager, turn, TEXT, "")).matches
        assert turn.review_change_feedback["rejections"][0]["reason_code"] == "target_mismatch"


@pytest.mark.parametrize("recipient", ["@player", PLAYER])
async def test_give_public_recipient_matches_review_but_preserves_canonical_owner(
    monkeypatch, recipient
):
    async with TestSessionLocal() as db:
        manager, turn = await published(
            db,
            [
                Take(tool="take_item", item_id="KEY"),
                Give(tool="give_item", item_id="KEY", recipient_id=recipient),
            ],
        )
        canonical = deepcopy(turn.action_outcomes)
        contract = runtime.contract_data(turn)
        effect = contract["LINA"]["authoritative_command_outcomes"][1]["effect"]
        assert effect["destination_owner"] == "@player"
        assert contract["current_execution_frame"]["entities"]["KEY"]["owner_id"] == "@player"
        reviewer(monkeypatch, [claim(turn, target_id="KEY", recipient_id="@player")])
        text = 'Lina: "This is for you."\nLina hands the key to the visitor.'
        assert (await rendering._review(manager, turn, text, "")).matches
        assert canonical["LINA"][1]["effect"]["destination_owner"] == PLAYER
        assert turn.action_outcomes == canonical
        assert (
            possession_snapshot(manager, await session_objects(db, manager.game_id)).owners["KEY"]
            == PLAYER
        )


@pytest.mark.parametrize("recipient", ["SECOND", PLAYER, "canonical_player_id"])
async def test_give_review_rejects_wrong_or_nonpublic_recipient_ids(monkeypatch, recipient):
    async with TestSessionLocal() as db:
        manager, turn = await published(
            db,
            [
                Take(tool="take_item", item_id="KEY"),
                Give(tool="give_item", item_id="KEY", recipient_id="@player"),
            ],
        )
        recipient = manager.avatar.id if recipient == "canonical_player_id" else recipient
        reviewer(monkeypatch, [claim(turn, target_id="KEY", recipient_id=recipient)])
        assert not (await rendering._review(manager, turn, TEXT, "")).matches
        assert turn.review_change_feedback["rejections"][0]["reason_code"] == "result_mismatch"


@pytest.mark.parametrize("target", [PLAYER, "@player", "avatar-id"])
def test_public_projection_handles_legacy_character_aliases_without_changing_source(target):
    record = {
        "tool": "approach",
        "effect": {"placement": {"relation": "near", "target_kind": "character", "target": target}},
    }
    before = deepcopy(record)
    projected = outcome_projection.project(
        record, {"@player": {"kind": "actor"}}, player_id="avatar-id"
    )
    assert projected["effect"]["placement"]["target"] == "@player"
    assert record == before


def test_actor_alias_conversion_never_rewrites_scene_object_targets():
    record = {
        "tool": "approach",
        "effect": {
            "placement": {"relation": "near", "target_kind": "scene_object", "target": PLAYER}
        },
    }
    projected = outcome_projection.project(record, {PLAYER: {"kind": "item"}})
    assert projected == record
