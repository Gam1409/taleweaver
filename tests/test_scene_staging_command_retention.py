"""Failed extraction cannot erase retained command facts belonging to other actors."""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest

from backend.engine.clothing.context import actor_records
from backend.engine.scene_staging import command_guard, provenance, shared
from backend.engine.scene_staging.commands import CommandProof, apply_command
from backend.engine.scene_staging.schema import Placement, SceneExtraction
from backend.engine.scene_staging.state import KEY, project
from backend.engine.visual_novel.config import VnSettings, write_settings
from tests.npc_control_support import bind_turn

CAST = [{"id": actor, "name": actor} for actor in ("hero", "LINA", "SECOND")]
TEXT = "Hero remains sitting. Second remains sitting. Lina crawls near Hero."


def command(host, actor, posture, *, source="old-input", target=None, kind="character"):
    proof = CommandProof(
        command_id=f"command-{actor}-{source}",
        actor_id=actor,
        scene_id="START",
        input_id=source,
        input_revision=f"{source}-revision",
        request_hash=sha256(f"{actor}:{source}".encode()).hexdigest(),
        operation="approach" if target else "set_pose",
    )
    host.state.entity_states = apply_command(
        host.state.entity_states,
        actor_id=actor,
        scene_id="START",
        cast=CAST,
        proof=proof,
        enabled=True,
        posture=posture,
        placement=Placement(relation="near", target_kind=kind, target=target) if target else None,
        scene_objects={"BENCH": "bench"},
    )


def fixture(*, current=True):
    state = SimpleNamespace(current_scene_id="START", entity_states={}, session_id="session")
    write_settings(state, VnSettings(scene_staging=True))
    rows = [
        SimpleNamespace(
            id=actor,
            name=actor,
            entity_type="NPC",
            current_scene_id="START",
            inventory=[],
            metadata_json={},
        )
        for actor in ("LINA", "SECOND")
    ]
    rows.append(
        SimpleNamespace(
            id="BENCH",
            name="bench",
            entity_type="OBJECT",
            current_scene_id="START",
            metadata_json={},
        )
    )
    host = SimpleNamespace(
        state=state,
        avatar=SimpleNamespace(id="hero", name="Hero", inventory=[], equipment={}),
        _vn_player_message_id="current-input",
    )
    for actor in ("hero", "SECOND", "LINA"):
        command(host, actor, "standing" if actor == "LINA" else "sitting")
    if current:
        command(host, "LINA", "on_all_fours", source="current-input", target="hero")
        host._chpm_turn = SimpleNamespace(
            input_id="current-input",
            simplified=False,
            decisions={"LINA": None},
            initial=SimpleNamespace(settings=SimpleNamespace(mode="live", action_tools=True)),
            action_outcomes={
                "LINA": [
                    {
                        "tool": "approach",
                        "status": "applied",
                        "effect": {
                            "posture": "on_all_fours",
                            "placement": {"target": "hero"},
                        },
                    }
                ]
            },
        )
    if current:
        bind_turn(host, host._chpm_turn)
    return host, rows


def fail_shared(host, rows, *, after_prepare=None):
    assert shared.begin(host, TEXT)
    shared.prepare(host, actor_records(host, rows), rows)
    if after_prepare:
        after_prepare()
    shared.complete(host, None, [])
    assert shared.consume(host, TEXT, completed=True)


def test_missing_shared_section_preserves_other_actors_and_current_command_with_exact_sources():
    host, rows = fixture()
    before = deepcopy(host.state.entity_states[KEY]["actors"])
    fail_shared(host, rows)
    actual = host.state.entity_states[KEY]
    assert project(host.state, CAST) == {
        "hero": {"posture": "sitting"},
        "SECOND": {"posture": "sitting"},
        "LINA": {
            "posture": "on_all_fours",
            "placement": {
                "relation": "near",
                "target_kind": "character",
                "target": "hero",
            },
        },
    }
    assert actual["actors"] == before
    assert actual["reason"] == "The shared response did not confirm staging."
    assert actual["command_protected_fields"] == {"LINA": ["placement", "posture"]}


def test_repeated_failures_without_current_commands_keep_prior_facts_projectable():
    host, rows = fixture(current=False)
    before = deepcopy(host.state.entity_states[KEY]["actors"])
    fail_shared(host, rows)
    fail_shared(host, rows)
    assert host.state.entity_states[KEY]["actors"] == before
    assert project(host.state, CAST)["hero"]["posture"] == "sitting"
    assert not command_guard.capture(host)


def test_failure_before_cast_preparation_keeps_the_existing_current_command_fallback():
    host, _rows = fixture()
    current = deepcopy(host.state.entity_states[KEY]["actors"]["LINA"])
    assert shared.begin(host, TEXT)
    shared.complete(host, None, [])
    assert shared.consume(host, TEXT, completed=True)
    assert host.state.entity_states[KEY]["actors"]["LINA"] == current
    assert set(host.state.entity_states[KEY]["actors"]) == {"LINA"}


def test_unprepared_failure_does_not_treat_unknown_object_scope_as_an_empty_room():
    host, _rows = fixture()
    command(
        host, "LINA", "on_all_fours", source="object-input", target="BENCH", kind="scene_object"
    )
    host._vn_player_message_id = host._chpm_turn.input_id = "object-input"
    bind_turn(host, host._chpm_turn)
    current = deepcopy(host.state.entity_states[KEY]["actors"]["LINA"])
    assert shared.begin(host, TEXT)
    shared.complete(host, None, [])
    assert shared.consume(host, TEXT, completed=True)
    assert host.state.entity_states[KEY]["actors"]["LINA"] == current


@pytest.mark.parametrize("clear", [False, True])
def test_a_valid_later_narrated_change_supersedes_a_prior_command(clear):
    host, rows = fixture(current=False)
    fail_shared(host, rows)
    text = "Hero stands up."
    shared.apply_extraction(
        host,
        text,
        CAST,
        rows,
        SceneExtraction(
            changes=[
                {
                    "entity_id": "hero",
                    "posture": None if clear else "standing",
                    "clear": clear,
                    "evidence": text,
                }
            ]
        ),
    )
    assert project(host.state, CAST)["hero"] == ({} if clear else {"posture": "standing"})


def alter_actor(host, rows, change):
    if change == "removed":
        rows[:] = [row for row in rows if row.id != "SECOND"]
        return
    key, value = {
        "hidden": ("is_hidden", True),
        "defeated": ("is_defeated", True),
        "absent": ("presence", "absent"),
        "away": ("current_scene_id", "OTHER"),
        "moved": ("spatial_position", "door"),
    }[change]
    host.state.entity_states["SECOND"] = {key: value}


@pytest.mark.parametrize("change", ["hidden", "defeated", "absent", "away", "moved", "removed"])
def test_failure_filters_a_no_longer_present_or_stable_actor(change):
    host, rows = fixture(current=False)
    fail_shared(host, rows, after_prepare=lambda: alter_actor(host, rows, change))
    assert "SECOND" not in host.state.entity_states[KEY]["actors"]
    assert project(host.state, CAST)["hero"]["posture"] == "sitting"


def alter_object(rows, change):
    if change == "removed":
        rows[:] = [row for row in rows if row.id != "BENCH"]
        return
    if change == "unchanged":
        return
    target = next(row for row in rows if row.id == "BENCH")
    key, value = {
        "hidden": ("is_hidden", True),
        "carried": ("is_in_inventory", True),
        "away": ("current_scene_id", "OTHER"),
    }[change]
    setattr(target, key, value)


@pytest.mark.parametrize("current", [False, True])
@pytest.mark.parametrize("change", ["unchanged", "hidden", "carried", "away", "removed"])
def test_object_target_retention_uses_current_rows_and_overrides(current, change):
    host, rows = fixture(current=False)
    command(host, "SECOND", "sitting", source="object-input", target="BENCH", kind="scene_object")
    if current:
        host._vn_player_message_id = "object-input"
        host._chpm_turn = SimpleNamespace(
            input_id="object-input",
            simplified=True,
            initial=SimpleNamespace(settings=SimpleNamespace(mode="live", action_tools=True)),
            action_outcomes={
                "SECOND": [
                    {
                        "tool": "approach",
                        "status": "applied",
                        "effect": {
                            "posture": "sitting",
                            "placement": {"target": "BENCH"},
                        },
                    }
                ]
            },
        )
        bind_turn(host, host._chpm_turn)
    fail_shared(host, rows, after_prepare=lambda: alter_object(rows, change))
    second = host.state.entity_states[KEY]["actors"]["SECOND"]
    assert ("placement" in second) is (change == "unchanged")
    assert second["posture"]["value"] == "sitting"


def test_failure_never_revives_retracted_sources():
    host, rows = fixture(current=False)
    provenance.retract(host.state, "old-input")
    fail_shared(host, rows)
    assert not host.state.entity_states[KEY]["actors"]
