"""Pose review reuses current owners without persisting classifications or private copies."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.clothing.context import actor_records
from backend.engine.narrated_items import evidence
from backend.engine.npc_actions import execution_frame, pose_audit, pose_audit_owner
from backend.engine.scene_continuity.schema import Action
from backend.engine.scene_staging import shared
from backend.engine.scene_staging.proposals import StagingProposal
from backend.engine.scene_staging.state import KEY
from tests.conftest import TestSessionLocal
from tests.test_scene_continuity import apply_to, read
from tests.test_scene_staging_action_authority import NARRATION, player_cause, real_sources


@pytest.mark.parametrize("valid", [False, True])
async def test_pose_preview_admits_only_current_external_owner_proof_without_mutation(valid):
    async with TestSessionLocal() as db:
        host, rows, cast, _ = await real_sources(db)
        host._chpm_turn.execution_frame = execution_frame.Frame(
            {},
            "START",
            0,
            {identifier: {"id": identifier, "kind": "actor"} for identifier in ("LINA", "SECOND")},
            None,
        )
        assert shared.begin(host, NARRATION)
        await shared.prepare_authority(host)
        actors = actor_records(host, rows)
        shared.prepare(host, actors, rows)
        cause = player_cause(host)
        if not valid:
            cause["passage_id"] = "missing-source"
        catalog = evidence.Catalog(NARRATION, scope="pose-audit-owner")
        staging = evidence.bind_staging(
            StagingProposal(
                changes=[
                    {
                        "entity_id": "SECOND",
                        "performer_id": "__player__",
                        "cause": cause,
                        "posture": "kneeling",
                        "evidence": next(iter(catalog.narration_passages)),
                    }
                ]
            ),
            catalog,
        )
        before = deepcopy(host.state.entity_states)

        preview = pose_audit_owner.preview(host, NARRATION, staging, actors, rows)

        assert host.state.entity_states == before
        assert preview.facts["SECOND"]["posture"] == ("kneeling" if valid else "standing")
        assert bool(preview.external.get("SECOND")) is valid
        assert bool(preview.rejected) is not valid
        if valid:
            shared.apply_extraction(
                host,
                NARRATION,
                cast,
                rows,
                staging,
                authority=host._shared_scene_staging.authority,
            )
            assert pose_audit_owner.facts(host, actors, rows) == preview.facts
            assert host.state.entity_states[KEY]["actors"]["SECOND"]["posture"]["cause"]


class NoCopy:
    def __deepcopy__(self, memo):
        raise AssertionError("An unrelated notebook must not be copied by pose review.")


async def test_pose_preview_without_changes_does_not_copy_unrelated_private_values():
    async with TestSessionLocal() as db:
        host, rows, _, _ = await real_sources(db)
        marker = NoCopy()
        host.state.entity_states = {**host.state.entity_states, "private_notebook": marker}
        actors = actor_records(host, rows)

        preview = pose_audit_owner.preview(host, NARRATION, None, actors, rows)

        assert not preview.external and not preview.rejected
        assert host.state.entity_states["private_notebook"] is marker


def test_contained_source_excerpt_retains_its_host_passage_anchor():
    narration = "The lamp flickers. Lina remains standing. A bell rings."
    catalog = evidence.Catalog(narration, scope="pose-contained-source")
    candidate = evidence.bind(
        {
            "final_frame_actions": [
                {
                    "actor_ids": ["LINA"],
                    "detail": "Lina remains standing.",
                    "evidence": "Lina remains standing.",
                    "poses": [
                        {
                            "actor_id": "LINA",
                            "basis": "current",
                            "posture": "standing",
                        }
                    ],
                }
            ]
        },
        narration,
        catalog=catalog,
    )
    action = Action.model_validate(candidate.final_frame_actions[0])
    proof = SimpleNamespace(occurrences=(("p0", 0, len(narration)),))

    assert action.evidence_span.start > 0
    assert pose_audit._passage(proof, action) == "p0"


@pytest.mark.parametrize("noncurrent", [False, True])
def test_transient_pose_classification_never_becomes_a_second_persisted_pose_owner(noncurrent):
    action = {
        "actor_ids": ["LINA"],
        "detail": "Lina points at the door.",
        "evidence": "Lina points at the door.",
        "poses": [],
        "timeframe": "noncurrent" if noncurrent else "current",
    }

    states, errors = apply_to(updates=[], actions=[action])

    assert not errors
    ledger = read(states)
    assert len(ledger.frame_actions) == int(not noncurrent)
    if not noncurrent:
        legacy = {key: value for key, value in action.items() if key not in {"poses", "timeframe"}}
        assert ledger.frame_actions[0].model_dump() == legacy
        assert ledger.frame_message_id == "reply"
    assert "poses" not in str(states)
