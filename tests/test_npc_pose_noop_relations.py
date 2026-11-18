"""Reissued pose proofs preserve relations unless the final pose or placement changes."""

from copy import deepcopy

import pytest

from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.visuals import session_objects
from backend.engine.npc_actions.contracts import Approach
from backend.engine.npc_actions.preparation import capture
from backend.engine.npc_actions.publication import publish
from backend.engine.scene_staging.commands import CommandProof, apply_command
from backend.engine.scene_staging.schema import Placement
from backend.engine.scene_staging.shared import _cast
from backend.engine.scene_staging.state import project
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.npc_control_support import bind_observation
from tests.test_npc_action_publication import fixture as stored_fixture
from tests.test_scene_staging_command_retention import CAST, command, fixture


@pytest.mark.parametrize(
    "posture,target,moved",
    [("standing", "BENCH", False), ("kneeling", "BENCH", True), ("kneeling", None, True)],
)
def test_dependent_relations_follow_actual_command_results(posture, target, moved):
    host, _ = fixture(current=False)
    command(host, "SECOND", "standing", source="first", target="BENCH", kind="scene_object")
    command(host, "LINA", "standing", source="second", target="SECOND")
    before = deepcopy(project(host.state, CAST))

    command(host, "SECOND", posture, source="third", target=target, kind="scene_object")

    after = project(host.state, CAST)
    assert after["LINA"]["posture"] == before["LINA"]["posture"]
    if moved:
        assert "placement" not in after["LINA"]
    else:
        assert after["SECOND"] == before["SECOND"]
        assert after["LINA"] == before["LINA"]


@pytest.mark.parametrize(
    "target,label,moved", [("OTHER_BENCH", "bench", True), ("BENCH", "renamed bench", False)]
)
def test_scene_object_identity_controls_movement_independently_of_display_labels(
    target, label, moved
):
    host, _ = fixture(current=False)
    command(host, "SECOND", "standing", source="first", target="BENCH", kind="scene_object")
    command(host, "LINA", "standing", source="second", target="SECOND")
    before = deepcopy(project(host.state, CAST))
    proof = CommandProof(
        command_id="new-approach",
        actor_id="SECOND",
        scene_id="START",
        input_id="new-input",
        request_hash="a" * 64,
        operation="approach",
    )

    host.state.entity_states = apply_command(
        host.state.entity_states,
        scene_id="START",
        cast=CAST,
        actor_id="SECOND",
        enabled=True,
        proof=proof,
        posture="standing",
        placement=Placement(relation="near", target_kind="scene_object", target=target),
        scene_objects={"BENCH": "bench", target: label},
    )

    after = project(host.state, CAST)
    if moved:
        assert after["SECOND"] == before["SECOND"]  # Display labels alone cannot prove no movement.
        assert "placement" not in after["LINA"]
    else:
        assert after["SECOND"]["placement"]["target"] == label
        assert after["LINA"] == before["LINA"]


async def test_real_publication_of_unchanged_approach_preserves_another_actor_relation():
    async with TestSessionLocal() as db:
        host, observed, _ = await stored_fixture(db)
        bind_observation(host, observed)
        write_settings(host.state, VnSettings(scene_staging=True))
        db.add(
            WorldEntity(
                id="BENCH",
                session_id=host.game_id,
                entity_type="OBJECT",
                name="bench",
                description="A fixed bench.",
                current_scene_id="START",
                is_portable=False,
            )
        )
        await db.commit()
        rows = await session_objects(db, host.game_id)
        cast = _cast(host, actor_records(host, rows), rows)
        for index, actor, target, kind in (
            (0, "SECOND", "BENCH", "scene_object"),
            (1, "LINA", "SECOND", "character"),
        ):
            host.state.entity_states = apply_command(
                host.state.entity_states,
                scene_id="START",
                cast=cast,
                actor_id=actor,
                enabled=True,
                proof=CommandProof(
                    command_id=f"seed-{index}",
                    actor_id=actor,
                    scene_id="START",
                    input_id=observed.message_id,
                    input_revision=observed.revision_id,
                    request_hash=observed.content_hash,
                    operation="approach",
                ),
                posture="standing",
                placement=Placement(relation="near", target_kind=kind, target=target),
                scene_objects={"BENCH": "bench"},
            )
        before = project(host.state, cast)
        draft = (await capture(host, await capture_views(host, ["SECOND"], observed), observed))[
            "SECOND"
        ]
        assert draft.execute(Approach(tool="approach", target_id="BENCH"))["status"] == "staged"
        assert project(host.state, cast) == before
        draft.approved = True

        assert (await publish(host, draft))[0]["status"] == "applied"

        assert project(host.state, cast)["SECOND"] == before["SECOND"]
        assert project(host.state, cast)["LINA"] == before["LINA"]
