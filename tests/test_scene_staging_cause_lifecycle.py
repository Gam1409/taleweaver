"""Accepted external pose causes keep real source identity through lifecycle changes."""

from copy import deepcopy

import pytest

from backend.engine.narrated_items import evidence
from backend.engine.scene_staging import attribution, provenance, shared
from backend.engine.scene_staging.proposals import StagingProposal
from backend.engine.scene_staging.state import KEY
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_scene_staging_action_authority import (
    NARRATION,
    apply_attributed,
    player_cause,
    real_sources,
)


async def saved_effect(db):
    host, rows, cast, player = await real_sources(db)
    await apply_attributed(host, rows, cast, cause=player_cause(host))
    reply = ChatMessage(
        session_id=host.game_id, role="assistant", content=NARRATION, scene_id="START"
    )
    db.add(reply)
    await db.commit()
    provenance.stamp(host.state, reply)
    return host, player, reply


async def test_stamping_and_copy_remap_preserve_the_distinct_performer_source():
    async with TestSessionLocal() as db:
        host, player, reply = await saved_effect(db)
        before = deepcopy(host.state.entity_states)
        fact = before[KEY]["actors"]["SECOND"]["posture"]
        assert fact["source_message_id"] == reply.id
        assert fact["cause"]["source_message_id"] == player.id
        assert fact["cause"]["source_revision_id"] == player.revision_id
        assert fact["cause"]["performer_id"] == host.avatar.id
        mapping = {player.id: "copied-player", reply.id: "copied-reply"}
        copied = provenance.remap(before, mapping)
        for kind in ("posture", "placement"):
            actual = copied[KEY]["actors"]["SECOND"][kind]
            assert actual["source_message_id"] == "copied-reply"
            assert actual["cause"]["source_message_id"] == "copied-player"
            assert actual["cause"]["source_hash"] == fact["cause"]["source_hash"]
        assert host.state.entity_states == before


@pytest.mark.parametrize("source", ["performer", "narration"])
async def test_retracting_either_real_source_cannot_retain_a_causally_orphaned_pose(source):
    async with TestSessionLocal() as db:
        host, player, reply = await saved_effect(db)
        provenance.retract(host.state, player.id if source == "performer" else reply.id)
        assert "SECOND" not in host.state.entity_states[KEY]["actors"]
        assert "SECOND" in host.state.entity_states[KEY]["unconfirmed_actors"]


async def test_copy_without_the_performer_source_marks_the_dependent_pose_unconfirmed():
    async with TestSessionLocal() as db:
        host, _, reply = await saved_effect(db)
        copied = provenance.remap(host.state.entity_states, {reply.id: "copied-reply"})
        assert "SECOND" not in copied[KEY]["actors"]
        assert "SECOND" in copied[KEY]["unconfirmed_actors"]


@pytest.mark.parametrize("performer", ["__player__", "SECOND"])
async def test_clear_with_new_fields_requires_external_authority_even_when_old_pose_is_unknown(
    performer,
):
    async with TestSessionLocal() as db:
        host, rows, cast, _ = await real_sources(db)
        host.state.entity_states[KEY]["actors"].pop("SECOND")
        scope = await attribution.capture(host)
        catalog = evidence.Catalog(NARRATION, scope="clear-new-pose")
        proposal = StagingProposal(
            changes=[
                {
                    "entity_id": "SECOND",
                    "performer_id": performer,
                    "cause": player_cause(host),
                    "clear": True,
                    "posture": "kneeling",
                    "evidence": next(iter(catalog.narration_passages)),
                }
            ]
        )
        resolved = evidence.bind_staging(proposal, catalog)
        scope = await attribution.refresh(host, scope)
        shared.apply_extraction(host, NARRATION, cast, rows, resolved, authority=scope)
        actors = host.state.entity_states[KEY]["actors"]
        if performer == "__player__":
            assert actors["SECOND"]["posture"]["value"] == "kneeling"
            assert actors["SECOND"]["posture"]["source_kind"] == "external_effect"
        else:
            assert "SECOND" not in actors
