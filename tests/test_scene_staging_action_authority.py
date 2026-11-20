"""Controlled pose changes require attributed current causes, not narrated plans."""

from hashlib import sha256
from types import SimpleNamespace

import pytest

from backend.engine import turn_controls
from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.chpm.schema import KernelState, Observation, Settings
from backend.engine.chpm.state import KEY as CHPM_KEY
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.visuals import session_objects
from backend.engine.narrated_items import evidence
from backend.engine.npc_actions.contracts import Interact, Pose
from backend.engine.npc_actions.preparation import capture as capture_actions
from backend.engine.npc_actions.publication import publish
from backend.engine.scene_staging import shared
from backend.engine.scene_staging.commands import CommandProof, apply_command
from backend.engine.scene_staging.proposals import StagingProposal
from backend.engine.scene_staging.schema import SceneExtraction
from backend.engine.scene_staging.state import KEY as STAGING_KEY
from backend.engine.scene_staging.state import project
from backend.engine.visual_novel import movement_sources
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.npc_control_support import bind_observation, bind_turn
from tests.test_npc_action_publication import fixture as publication_fixture
from tests.test_scene_staging_command_retention import CAST, command, fixture


def controlled(host, actor="SECOND", outcomes=None):
    host._chpm_turn = SimpleNamespace(
        input_id="current-input",
        simplified=False,
        decisions={actor: None},
        initial=SimpleNamespace(settings=SimpleNamespace(mode="live", action_tools=True)),
        action_outcomes={actor: outcomes or []},
    )
    bind_turn(host, host._chpm_turn)


def kneel(host, rows, actor="SECOND"):
    text = "Second kneels beside the bench."
    shared.apply_extraction(
        host,
        text,
        CAST,
        rows,
        SceneExtraction(
            changes=[
                {
                    "entity_id": actor,
                    "posture": "kneeling",
                    "placement": {
                        "relation": "beside",
                        "target_kind": "scene_object",
                        "target": "bench",
                    },
                    "evidence": text,
                }
            ]
        ),
    )


def test_approved_empty_plan_cannot_publish_a_new_unattributed_pose():
    host, rows = fixture(current=False)
    command(host, "SECOND", "standing", source="prior-standing")
    controlled(host)

    kneel(host, rows)

    assert project(host.state, CAST)["SECOND"] == {"posture": "standing"}
    assert host._chpm_turn.action_outcomes == {"SECOND": []}


@pytest.mark.parametrize("active", [False, True])
def test_legacy_and_uncontrolled_actor_changes_remain_eligible(active):
    host, rows = fixture(current=False)
    if active:
        controlled(host, "LINA")

    kneel(host, rows)

    assert project(host.state, CAST)["SECOND"]["posture"] == "kneeling"


def test_an_empty_plan_allows_an_unchanged_pose_echo():
    host, rows = fixture(current=False)
    command(host, "SECOND", "standing", source="prior-standing")
    controlled(host)
    text = "Second remains standing."

    shared.apply_extraction(
        host,
        text,
        CAST,
        rows,
        SceneExtraction(changes=[{"entity_id": "SECOND", "posture": "standing", "evidence": text}]),
    )

    assert project(host.state, CAST)["SECOND"] == {"posture": "standing"}


def test_another_actors_movement_invalidates_a_commanded_relation_without_erasing_pose():
    host, rows = fixture(current=False)
    command(host, "LINA", "on_all_fours", source="current-input", target="SECOND")
    controlled(
        host,
        "LINA",
        outcomes=[
            {
                "tool": "approach",
                "status": "applied",
                "effect": {"posture": "on_all_fours", "placement": {"target": "SECOND"}},
            }
        ],
    )

    kneel(host, rows)

    actual = project(host.state, CAST)
    assert actual["SECOND"]["posture"] == "kneeling"
    assert actual["LINA"] == {"posture": "on_all_fours"}


@pytest.mark.parametrize(
    "posture,relation,clear,moved,text",
    [
        ("sitting", "near", False, False, "Second remains sitting near the bench."),
        ("sitting", "near", True, False, "Second remains sitting near the bench."),
        ("sitting", None, False, False, "Second remains sitting."),
        ("sitting", "beside", False, True, "Second sits beside the bench."),
        ("kneeling", None, False, True, "Second kneels."),
        (None, None, True, True, "Second moves, leaving his final posture and place unclear."),
    ],
)
def test_dependent_command_relation_changes_only_when_target_final_staging_changes(
    posture, relation, clear, moved, text
):
    host, rows = fixture(current=False)
    command(host, "SECOND", "sitting", source="prior-second", target="BENCH", kind="scene_object")
    command(host, "LINA", "on_all_fours", source="current-input", target="SECOND")
    controlled(
        host,
        "LINA",
        outcomes=[
            {
                "tool": "approach",
                "status": "applied",
                "effect": {"posture": "on_all_fours", "placement": {"target": "SECOND"}},
            }
        ],
    )
    before = project(host.state, CAST)
    shared.apply_extraction(
        host,
        text,
        CAST,
        rows,
        SceneExtraction(
            changes=[
                {
                    "entity_id": "SECOND",
                    "posture": posture,
                    "clear": clear,
                    "evidence": text,
                    "placement": {
                        "relation": relation,
                        "target_kind": "scene_object",
                        "target": "bench",
                    }
                    if relation
                    else None,
                }
            ]
        ),
    )
    actual = project(host.state, CAST)
    assert actual["LINA"]["posture"] == "on_all_fours"
    if moved:
        assert "placement" not in actual["LINA"]
    else:
        assert actual["SECOND"] == before["SECOND"]
        assert actual["LINA"] == before["LINA"]


PLAYER_INPUT = "I push Second down to his knees beside the bench."
NARRATION = "Second raises a hand while the player pushes him down beside the bench."


async def real_sources(db, *, interaction_target=None, current_pose=False):
    host, old, _ = await publication_fixture(db)
    write_settings(host.state, VnSettings(scene_staging=True))
    initial = KernelState(
        settings=Settings(
            mode="live",
            workflow="integrated",
            action_tools=True,
            actor_ids=["LINA", "SECOND"],
            agent_steps=2,
        )
    )
    host.state.entity_states = {**host.state.entity_states, CHPM_KEY: initial.model_dump()}
    rows = await session_objects(db, host.game_id)
    cast = shared._cast(host, actor_records(host, rows), rows)
    host.state.entity_states = apply_command(
        host.state.entity_states,
        scene_id="START",
        cast=cast,
        actor_id="SECOND",
        proof=CommandProof(
            command_id="prior-standing",
            actor_id="SECOND",
            scene_id="START",
            input_id=old.message_id,
            input_revision=old.revision_id,
            request_hash=old.content_hash,
            operation="set_pose",
        ),
        enabled=True,
        posture="standing",
    )
    message = ChatMessage(
        session_id=host.game_id, role="user", content=PLAYER_INPUT, scene_id="START"
    )
    db.add(message)
    await db.commit()
    host._vn_player_message_id = message.id
    turn_controls.begin(host)
    observed = Observation(
        session_id=host.game_id,
        message_id=message.id,
        revision_id=message.revision_id,
        content_hash=sha256(message.content.encode()).hexdigest(),
        sequence=1,
        scene_id="START",
        minute=0,
        player_request=message.content,
    )
    bind_observation(host, observed)
    views = await capture_views(host, ["LINA", "SECOND"], observed)
    drafts = await capture_actions(host, views, observed)
    if interaction_target:
        assert (
            drafts["LINA"].execute(
                Interact(
                    tool="interact", target_id=interaction_target, action="Push the target down."
                )
            )["status"]
            == "staged"
        )
    if current_pose:
        assert (
            drafts["SECOND"].execute(Pose(tool="set_pose", posture="standing"))["status"]
            == "staged"
        )
    outcomes = {}
    for actor, draft in drafts.items():
        draft.approved = True
        outcomes[actor] = await publish(host, draft)
    host._chpm_turn = SimpleNamespace(
        initial=initial,
        input_id=message.id,
        simplified=False,
        decisions={actor: None for actor in drafts},
        action_drafts=drafts,
        action_outcomes=outcomes,
        control=turn_controls.scope(host, "narration_review", observation=observed),
    )
    await db.commit()
    await movement_sources.prepare(host)
    return host, rows, cast, message


def player_cause(host, basis="resolved_external_effect"):
    source = host._vn_movement_sources["current_player_action"]
    return {
        "kind": "current_player_action",
        "passage_id": next(iter(source.passages)),
        "basis": basis,
    }


async def apply_attributed(
    host, rows, cast, *, performer="__player__", cause=None, alter=None, narration=NARRATION
):
    assert shared.begin(host, narration)
    await shared.prepare_authority(host)
    context = shared.prepare(host, actor_records(host, rows), rows)
    catalog = evidence.Catalog(narration, scope=f"{host.game_id}:staging-authority")
    candidate = StagingProposal(
        changes=[
            {
                "entity_id": "SECOND",
                "performer_id": performer,
                "cause": cause,
                "posture": "kneeling",
                "placement": {
                    "relation": "beside",
                    "target_kind": "scene_object",
                    "target": "bench",
                },
                "evidence": next(iter(catalog.narration_passages)),
            }
        ],
        props=[],
        explicit=[],
    )
    resolved = evidence.bind_staging(candidate, catalog)
    shared.propose(host, {"staging": resolved.model_dump()})
    if alter:
        await alter()
    await shared.refresh_authority(host)
    assert shared.consume(host, narration, completed=True)
    return context


async def test_current_player_effect_is_resolved_independently_of_an_own_gesture_in_same_passage():
    async with TestSessionLocal() as db:
        host, rows, cast, message = await real_sources(db)
        assert host._chpm_turn.action_outcomes["SECOND"] == []

        context = await apply_attributed(host, rows, cast, cause=player_cause(host))

        assert "SECOND" in str(context)
        assert project(host.state, cast)["SECOND"] == {
            "posture": "kneeling",
            "placement": {"relation": "beside", "target_kind": "scene_object", "target": "bench"},
        }
        fact = host.state.entity_states[STAGING_KEY]["actors"]["SECOND"]["posture"]
        assert fact["source_kind"] == "external_effect"
        assert fact["cause"]["source_message_id"] == message.id
        assert fact["cause"]["source_revision_id"] == message.revision_id
        assert host._chpm_turn.action_outcomes["SECOND"] == []


async def test_external_effect_is_not_restored_away_by_a_current_pose_command():
    async with TestSessionLocal() as db:
        host, rows, cast, _ = await real_sources(db, current_pose=True)
        receipt = host._chpm_turn.action_outcomes["SECOND"][0]
        assert receipt["status"] == "applied" and receipt["effect"]["posture"] == "standing"

        await apply_attributed(host, rows, cast, cause=player_cause(host))

        assert project(host.state, cast)["SECOND"]["posture"] == "kneeling"
        assert receipt["effect"]["posture"] == "standing"


@pytest.mark.parametrize("performer", [None, "SECOND", "START", "invented"])
async def test_missing_self_or_foreign_performer_cannot_relabel_a_controlled_pose(performer):
    async with TestSessionLocal() as db:
        host, rows, cast, _ = await real_sources(db)

        await apply_attributed(host, rows, cast, performer=performer, cause=player_cause(host))

        assert project(host.state, cast)["SECOND"] == {"posture": "standing"}


@pytest.mark.parametrize("basis", ["attempt", "intention", "uncertain"])
async def test_an_unresolved_player_source_never_establishes_target_success(basis):
    async with TestSessionLocal() as db:
        host, rows, cast, _ = await real_sources(db)

        await apply_attributed(host, rows, cast, cause=player_cause(host, basis))

        assert project(host.state, cast)["SECOND"] == {"posture": "standing"}


@pytest.mark.parametrize("change", ["input", "attempt", "revision", "hash", "scene"])
async def test_player_effect_source_is_rechecked_after_extraction(change):
    async with TestSessionLocal() as db:
        host, rows, cast, message = await real_sources(db)

        async def alter():
            if change == "input":
                host._vn_player_message_id = "another-input"
            if change == "attempt":
                turn_controls.begin(host)
            if change == "revision":
                message.revision_id = "another-revision"
            if change == "hash":
                message.content += " A changed action."
            if change == "scene":
                message.scene_id = "another-scene"
            await db.commit()

        await apply_attributed(host, rows, cast, cause=player_cause(host), alter=alter)

        assert project(host.state, cast)["SECOND"] == {"posture": "standing"}


async def test_another_npcs_attempt_requires_a_separate_current_resolved_consequence():
    async with TestSessionLocal() as db:
        host, rows, cast, _ = await real_sources(db, interaction_target="SECOND")
        operation = host._chpm_turn.action_outcomes["LINA"][0]
        assert operation["status"] == "attempted"
        assert project(host.state, cast)["SECOND"] == {"posture": "standing"}

        await apply_attributed(
            host,
            rows,
            cast,
            performer="LINA",
            narration="Second raises a hand while Lina pushes him down beside the bench.",
            cause={
                "kind": "actor_operation",
                "operation_id": operation["operation_id"],
                "basis": "resolved_external_effect",
            },
        )

        assert project(host.state, cast)["SECOND"]["posture"] == "kneeling"
        assert host._chpm_turn.action_outcomes["LINA"][0]["status"] == "attempted"


@pytest.mark.parametrize(
    "source", ["foreign_operation", "wrong_performer", "wrong_target", "attempt"]
)
async def test_other_actor_sources_cannot_borrow_unrelated_or_unresolved_attempts(source):
    async with TestSessionLocal() as db:
        target = "@player" if source == "wrong_target" else "SECOND"
        host, rows, cast, _ = await real_sources(db, interaction_target=target)
        operation = host._chpm_turn.action_outcomes["LINA"][0]
        performer = "__player__" if source == "wrong_performer" else "LINA"
        identifier = (
            "foreign-operation" if source == "foreign_operation" else operation["operation_id"]
        )
        await apply_attributed(
            host,
            rows,
            cast,
            performer=performer,
            cause={
                "kind": "actor_operation",
                "operation_id": identifier,
                "basis": "attempt" if source == "attempt" else "resolved_external_effect",
            },
        )

        assert project(host.state, cast)["SECOND"] == {"posture": "standing"}
        assert host._chpm_turn.action_outcomes["LINA"][0]["status"] == "attempted"


@pytest.mark.parametrize("passage_id", [None, "history:p0", "player:p999"])
async def test_nonself_identity_requires_a_current_supplied_player_source_handle(passage_id):
    async with TestSessionLocal() as db:
        host, rows, cast, _ = await real_sources(db)
        cause = {**player_cause(host), "passage_id": passage_id} if passage_id else None

        await apply_attributed(host, rows, cast, cause=cause)

        assert project(host.state, cast)["SECOND"] == {"posture": "standing"}
