"""Object bindings follow public room identities across extraction and retained poses."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import host_scene, observable_state
from backend.engine.clothing.context import actor_records
from backend.engine.scene_continuity.scope import SceneScope
from backend.engine.scene_staging import runtime, shared
from backend.engine.scene_staging.proposals import StagingProposal
from backend.engine.scene_staging.state import KEY, narration_block, project
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.engine.visual_novel.continuity import PLAYER
from tests.observable_state_support import entity, world
from tests.test_chpm_kernel import observation

TEXT = "Hero sits on the wooden bench."
PLACEMENT = {"relation": "on", "target_kind": "scene_object", "target": "FURNITURE"}


def room():
    manager, rows = world()
    write_settings(manager.state, VnSettings(scene_staging=True))
    for row in rows:
        row.spatial_position = None
    rows.append(entity("FURNITURE", name="oak bench", is_portable=False))
    return manager, rows


def prepare(manager, rows, text=TEXT):
    assert shared.begin(manager, text)
    return shared.prepare(manager, actor_records(manager, rows), rows)


def finish(manager, changes, text=TEXT):
    shared.propose(manager, {"staging": {"changes": changes, "props": [], "explicit": []}})
    assert shared.consume(manager, text, completed=True)
    return manager.state.entity_states[KEY]


def pose(**fields):
    return {"entity_id": PLAYER, "evidence": TEXT, **fields}


def test_fixed_object_id_is_published_and_bound_with_the_current_label_and_source():
    manager, rows = room()
    manager.state.entity_states["FURNITURE"] = {"name": "window bench"}
    context = prepare(manager, rows)
    assert context["scene_objects"]["FURNITURE"] == "window bench"
    row = finish(manager, [pose(posture="sitting", placement=PLACEMENT)])["actors"]["avatar"]
    assert row["placement"]["target_id"] == "FURNITURE"
    assert row["placement"]["target"] == "window bench"
    assert row["placement"]["evidence"] == TEXT
    manager.state.entity_states["FURNITURE"]["name"] = "garden bench"
    context = prepare(manager, rows)
    assert context["previous_staging"][PLAYER]["placement"] == PLACEMENT
    row = finish(manager, [])["actors"]["avatar"]
    assert row["placement"]["target"] == "garden bench"
    assert row["placement"]["target_id"] == "FURNITURE"


@pytest.mark.parametrize("clear", [False, True])
def test_invalid_target_keeps_grounded_posture_and_drops_stale_placement(clear):
    manager, rows = room()
    prepare(manager, rows)
    finish(manager, [pose(posture="sitting", placement=PLACEMENT)])
    prepare(manager, rows)
    result = finish(
        manager, [pose(posture="sitting", clear=clear, placement={**PLACEMENT, "target": "absent"})]
    )
    assert result["rejected"] == 1
    assert result["unconfirmed_actors"] == []
    assert project(manager.state, [{"id": "avatar"}]) == {"avatar": {"posture": "sitting"}}


@pytest.mark.parametrize("conflict", [False, True])
def test_only_actionable_duplicates_can_invalidate_a_pose(conflict):
    manager, rows = room()
    prepare(manager, rows)
    second = (
        pose(posture="standing") if conflict else pose(posture=None, placement=None, clear=False)
    )
    result = finish(manager, [pose(posture="sitting", placement=PLACEMENT), second])
    if conflict:
        assert result["unconfirmed_actors"] == ["avatar"]
        assert result["rejected"] == 2
        return
    assert result["rejected"] == 0 and not result["unconfirmed_actors"]
    assert result["actors"]["avatar"]["placement"]["target_id"] == "FURNITURE"


def test_hidden_carried_contained_and_undiscovered_targets_are_unavailable_even_if_quoted():
    manager, rows = room()
    rows.extend([entity("UNBUILT", item_type="CONSTRUCTABLE"), entity("CONCEALED")])
    manager.avatar.equipment = {"Hands": "FURNITURE"}
    private = {
        "HIDDEN",
        "AWAY",
        "FLASK",
        "OTHER_COAT",
        "PLAYER_COAT",
        "CONCEALED",
        "FURNITURE",
        "UNBUILT",
    }
    for identifier in sorted(private):
        text = f"Hero sits on {identifier}."
        context = prepare(manager, rows, text)
        assert private.isdisjoint(context["scene_objects"])
        result = finish(
            manager,
            [pose(evidence=text, posture="sitting", placement={**PLACEMENT, "target": identifier})],
            text,
        )
        assert result["rejected"] == 1
        assert "placement" not in result["actors"]["avatar"]
    manager.state.entity_states["UNBUILT"] = {"is_hidden": False}
    assert "UNBUILT" in prepare(manager, rows)["scene_objects"]


def test_stale_bound_id_is_pruned_from_inputs_and_output_while_textual_scenery_survives():
    manager, rows = room()
    other = "Other rests beside the stone wall."
    text = f"{TEXT} {other}"
    prepare(manager, rows, text)
    finish(
        manager,
        [
            pose(posture="sitting", placement=PLACEMENT),
            pose(
                entity_id="other",
                evidence=other,
                placement={
                    "relation": "beside",
                    "target_kind": "scene_object",
                    "target": "stone wall",
                },
            ),
        ],
        text,
    )
    manager.avatar.inventory.append("FURNITURE")
    context = prepare(manager, rows)
    assert "FURNITURE" not in context["scene_objects"]
    assert context["previous_staging"][PLAYER] == {"posture": "sitting"}
    assert "oak bench" not in narration_block(manager.state, rows, manager.avatar)
    result = finish(manager, [])
    assert "placement" not in result["actors"]["avatar"]
    legacy = result["actors"]["other"]["placement"]
    assert legacy["target"] == "stone wall" and "target_id" not in legacy


def test_newly_revealed_id_must_have_been_offered_and_a_removed_id_cannot_become_literal():
    manager, rows = room()
    text = "Hero sits on FURNITURE. Another sits near HIDDEN."
    context = prepare(manager, rows, text)
    assert "FURNITURE" in context["scene_objects"] and "HIDDEN" not in context["scene_objects"]
    rows.pop()
    manager.state.entity_states["HIDDEN"] = {"is_hidden": False}
    result = finish(
        manager,
        [
            pose(evidence=text, posture="sitting", placement=PLACEMENT),
            pose(
                entity_id="other",
                evidence=text,
                posture="sitting",
                placement={**PLACEMENT, "target": "HIDDEN"},
            ),
        ],
        text,
    )
    assert result["rejected"] == 2
    assert all("placement" not in result["actors"][key] for key in ("avatar", "other"))


async def test_large_room_catalog_is_bounded_and_unoffered_ids_cannot_be_guessed(monkeypatch):
    manager, rows = room()
    manager.db, manager.user = SimpleNamespace(), SimpleNamespace()
    monkeypatch.setattr(runtime, "session_objects", AsyncMock(return_value=rows))
    monkeypatch.setattr(runtime, "release_for_model", AsyncMock())
    monkeypatch.setattr(runtime, "role_timeout", lambda *_: 10)
    monkeypatch.setattr(
        "backend.engine.gameplay.world.AdventureLogic.build_session_entities",
        AsyncMock(return_value=[]),
    )
    model = AsyncMock(
        return_value=StagingProposal(
            changes=[pose(entity_id="avatar", posture="sitting", placement=PLACEMENT)],
            props=[],
            explicit=[],
        )
    )
    monkeypatch.setattr(
        runtime.GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(model="mock", aexecute_complex_task=model),
    )
    # First record the bench so it stays selectable when the room catalog grows.
    prepare(manager, rows)
    finish(manager, [pose(posture="sitting", placement=PLACEMENT)])
    rows.extend(entity(f"FIXTURE-{i:04d}", name="x" * 100, is_portable=False) for i in range(900))
    context = prepare(manager, rows)
    assert context["scene_objects"]["FURNITURE"] == "oak bench"
    assert len(json.dumps(context["scene_objects"])) < 16000
    omitted = next(
        row.id
        for row in rows
        if row.id.startswith("FIXTURE-") and row.id not in context["scene_objects"]
    )
    result = finish(
        manager,
        [pose(entity_id="other", posture="sitting", placement={**PLACEMENT, "target": omitted})],
    )
    assert result["rejected"] == 1 and "placement" not in result["actors"]["other"]
    await runtime.reconcile_narration(manager, TEXT, completed=True)
    model.assert_awaited_once()
    standalone = json.loads(model.await_args.args[1])
    assert standalone["scene_objects"] == context["scene_objects"]


def test_different_objects_with_the_same_public_name_invalidate_dependent_relations():
    manager, rows = room()
    rows.append(entity("SECOND_BENCH", name="oak bench", is_portable=False))
    other = "Other stands beside Hero."
    text = f"{TEXT} {other}"
    prepare(manager, rows, text)
    finish(
        manager,
        [
            pose(posture="sitting", placement=PLACEMENT),
            pose(
                entity_id="other",
                evidence=other,
                placement={"relation": "beside", "target_kind": "character", "target": PLAYER},
            ),
        ],
        text,
    )
    prepare(manager, rows)
    result = finish(
        manager, [pose(posture="sitting", placement={**PLACEMENT, "target": "SECOND_BENCH"})]
    )
    assert "placement" not in result["actors"]["other"]


@pytest.mark.parametrize("source", ["inspection", "memory"])
def test_observer_reads_refresh_bound_room_objects_before_another_narrator_turn(source):
    manager, rows = room()
    prepare(manager, rows)
    finish(manager, [pose(posture="sitting", placement=PLACEMENT)])
    manager._scene_continuity_scope = SceneScope(
        "room", frozenset({"npc", PLAYER, "FURNITURE"}), "", tuple(rows)
    )

    def read_player():
        if source == "inspection":
            return observable_state.project(manager, rows, "npc", observation()).entities["@player"]
        facts = host_scene.capture(manager, rows[0], {"npc": "NPC"})
        return next(
            row.model_dump(exclude_none=True)
            for row in facts.character_poses
            if row.entity_id == "@player"
        )

    assert read_player()["placement"]["target"] == (
        "FURNITURE" if source == "inspection" else "oak bench"
    )
    manager.state.entity_states["FURNITURE"] = {"name": "garden bench"}
    assert read_player()["placement"]["target"] == (
        "FURNITURE" if source == "inspection" else "garden bench"
    )
    manager.avatar.inventory.append("FURNITURE")
    assert "placement" not in read_player()
    assert read_player()["posture"] == "sitting"


@pytest.mark.parametrize("label", ["oak bench", "Oak Bench"])
def test_quoted_labels_cannot_bypass_an_ambiguous_registered_object_identity(label):
    manager, rows = room()
    rows.append(entity("SECOND_BENCH", name="oak bench", is_portable=False))
    text = f"Hero sits on the {label}."
    prepare(manager, rows, text)
    result = finish(
        manager,
        [pose(evidence=text, posture="sitting", placement={**PLACEMENT, "target": label})],
        text,
    )
    assert result["rejected"] == 1
    assert result["actors"]["avatar"]["posture"]["value"] == "sitting"
    assert "placement" not in result["actors"]["avatar"]
