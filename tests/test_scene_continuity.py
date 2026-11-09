"""Processes, lasting consequences, observer boundaries and source lifecycle."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.scene_continuity.ledger import apply, read
from backend.engine.scene_continuity.lifecycle import remap, retract
from backend.engine.scene_continuity.npc import observations
from backend.engine.scene_continuity.presentation import project, visual_facts
from backend.engine.scene_continuity.schema import KEY, Ledger

TEXT = "The kettle starts boiling. Steam fogs the window. Lina points at the door."
ROOM = "Cobalt mosaic walls and warm brass ceiling lamps. Lina wears an old red dress."


def message(identifier="reply", text=TEXT):
    return SimpleNamespace(id=identifier, content=text, revision_id=None)


def update(**extra):
    return {
        "operation": "record",
        "key": "boiling",
        "kind": "process",
        "subject_id": "KETTLE",
        "detail": "Kettle is boiling",
        "visual_detail": "Steam rises from the kettle",
        "visibility": "public",
        "evidence": "The kettle starts boiling.",
        **extra,
    }


def apply_to(states=None, updates=None, actions=None, minute=10, reply=None):
    return apply(
        states,
        [update()] if updates is None else updates,
        actions or [],
        message=reply or message(),
        scene_id="LAB",
        scene_description=ROOM,
        session_id="session",
        minute=minute,
        targets={"LAB", "KETTLE", "LINA", "WINDOW", "__player__"},
    )


def state(states, minute=10):
    return SimpleNamespace(entity_states=states, current_scene_id="LAB", in_game_time=minute)


def test_twenty_silent_turns_preserve_process_and_cause_ending_keeps_effect():
    saved, errors = apply_to()
    assert not errors
    process = next(iter(read(saved).records.values()))
    effect = update(
        key="fog",
        kind="effect",
        subject_id="WINDOW",
        detail="Window is fogged",
        visual_detail="Fogged glass",
        cause_id=process.id,
        evidence="Steam fogs the window.",
    )
    saved, errors = apply_to(saved, [effect], reply=message("effect"))
    assert not errors
    for index in range(20):
        saved, errors = apply_to(
            saved, [], reply=message(f"dialogue-{index}", "Lina answers quietly.")
        )
        assert not errors
        assert read(saved).records[process.id] == process
    saved, errors = apply_to(
        saved,
        [
            {
                "operation": "end",
                "record_id": process.id,
                "evidence": "The kettle stops boiling.",
                "visibility": "public",
            }
        ],
        reply=message("end", "The kettle stops boiling."),
    )
    assert not errors
    rows = read(saved).records
    assert rows[process.id].status == "ended"
    assert next(row for row in rows.values() if row.kind == "effect").status == "active"
    assert Ledger.model_validate_json(read(saved).model_dump_json()) == read(saved)


def test_game_time_marks_expired_process_unconfirmed_without_inventing_resolution():
    saved, errors = apply_to(updates=[update(review_after_minutes=5)])
    assert not errors
    assert project(state(saved, 14))["facts"][0]["status"] == "active"
    assert project(state(saved, 15))["facts"][0]["status"] == "needs_confirmation"
    assert project(state(saved, 43210))["facts"][0]["status"] == "needs_confirmation"
    assert read(saved).records[next(iter(read(saved).records))].status == "active"
    assert not visual_facts(state(saved, 15), {"LAB", "KETTLE"}, ROOM, "reply")["scene_facts"]


def test_environment_has_separate_source_and_frame_action_does_not_persist_by_silence():
    environment = update(
        key="room",
        kind="environment",
        subject_id="LAB",
        source="scene_description",
        detail="Cobalt mosaic walls and warm brass ceiling lamps.",
        visual_detail="Cobalt mosaic walls and warm brass ceiling lamps.",
        evidence="Cobalt mosaic walls and warm brass ceiling lamps.",
    )
    action = {
        "actor_ids": ["LINA"],
        "detail": "Lina points at the door.",
        "evidence": "Lina points at the door.",
    }
    saved, errors = apply_to(updates=[environment], actions=[action])
    assert not errors
    visual = visual_facts(state(saved), {"LAB", "LINA"}, ROOM, "reply")
    assert "Cobalt" in str(visual) and "old red dress" not in str(visual)
    assert visual["visible_action"] == action["detail"]
    assert not visual_facts(state(saved), {"LAB", "LINA"}, "Changed room", "reply")["scene_facts"]
    saved, errors = apply_to(saved, [], reply=message("later", "Lina nods."))
    assert not errors
    assert not visual_facts(state(saved), {"LAB", "LINA"}, ROOM, "later")["visible_action"]
    assert len(read(saved).records) == 1


def test_npc_and_image_never_receive_private_cause_and_absent_subjects():
    private = update(
        visibility="private", observers=["LINA"], visual_detail="", detail="Hidden cause"
    )
    saved, errors = apply_to(updates=[private])
    cause = next(iter(read(saved).records))
    saved, errors = apply_to(
        saved,
        [
            update(
                key="fog",
                kind="effect",
                subject_id="WINDOW",
                detail="Fogged window",
                cause_id=cause,
            )
        ],
        reply=message("fog"),
    )
    assert not errors
    scope = {"LAB", "KETTLE", "LINA", "WINDOW"}
    unknown = project(state(saved), actor_id="MIKI", targets=scope)
    assert "Hidden cause" not in str(unknown) and "cause_id" not in str(unknown)
    assert any(row.detail == "Hidden cause" for row in observations(state(saved), "LINA", scope))
    assert "Hidden cause" not in str(visual_facts(state(saved), scope, ROOM, "fog"))
    assert not project(state(saved), actor_id="MIKI", targets={"LAB"})["facts"]
    away = state(saved)
    away.current_scene_id = "HALL"
    assert not project(away, actor_id="LINA")["facts"]


def test_invalid_candidates_do_not_erase_good_facts_or_rewrite_sources():
    saved, errors = apply_to(
        updates=[update(evidence="Paraphrased quote"), update(subject_id="ABSENT"), update()]
    )
    assert len(errors) == 2 and len(read(saved).records) == 1
    original = deepcopy(saved)
    repeated, errors = apply_to(saved)
    assert repeated == original and not errors
    changed, errors = apply_to(
        saved,
        [
            {
                "operation": "end",
                "record_id": next(iter(read(saved).records)),
                "evidence": "Imagined ending",
            }
        ],
        reply=message("bad"),
    )
    assert errors and read(changed).records == read(original).records


def test_copy_and_retraction_preserve_records_but_revoke_invalid_evidence():
    saved, _ = apply_to()
    copied = remap(saved, {"reply": "copied"})
    assert next(iter(read(copied).records.values())).origin.source_id == "copied"
    assert next(iter(read(remap(saved, {})).records.values())).status == "unconfirmed"
    current = state(copied)
    retract(current, "copied")
    assert next(iter(read(current.entity_states).records.values())).status == "unconfirmed"
    assert read(current.entity_states).frame_actions == []
    assert read({}) == Ledger()


def test_invalid_persisted_state_is_preserved():
    broken = {KEY: {"version": 99}}
    with pytest.raises(ValueError):
        apply_to(broken)
    assert broken == {KEY: {"version": 99}}


def test_full_ledger_and_oversized_batch_keep_every_previous_record():
    from backend.engine.scene_continuity.schema import MAX_RECORDS

    saved, _ = apply_to()
    ledger = read(saved)
    prototype = next(iter(ledger.records.values()))
    ledger.records = {
        f"fact-{index}": prototype.model_copy(update={"id": f"fact-{index}", "key": f"key-{index}"})
        for index in range(MAX_RECORDS)
    }
    saved = {KEY: Ledger.model_validate(ledger.model_dump()).model_dump()}
    original = read(saved).records
    changed, errors = apply_to(saved, [update(key="overflow")], reply=message("full"))
    assert errors and read(changed).records == original
    changed, errors = apply_to(
        saved, [update(key=str(index)) for index in range(13)], reply=message("batch")
    )
    assert errors and read(changed).records == original


def test_new_arrival_does_not_learn_an_ended_event_without_witnessing_it():
    saved, _ = apply_to()
    identifier = next(iter(read(saved).records))
    saved, errors = apply_to(
        saved,
        [
            {
                "operation": "end",
                "record_id": identifier,
                "evidence": "The kettle stops boiling.",
                "visibility": "public",
            }
        ],
        reply=message("ended", "The kettle stops boiling."),
    )
    assert not errors
    assert not observations(state(saved), "NEW_ARRIVAL", {"LAB", "KETTLE"})
    assert project(state(saved), actor_id="__player__")["facts"][0]["status"] == "ended"


def test_time_cannot_move_backwards_inside_an_existing_record():
    saved, _ = apply_to(minute=100)
    identifier = next(iter(read(saved).records))
    changed, errors = apply_to(
        saved,
        [{"operation": "end", "record_id": identifier, "evidence": "The kettle stops boiling."}],
        minute=99,
        reply=message("backwards", "The kettle stops boiling."),
    )
    assert errors and read(changed).records == read(saved).records
