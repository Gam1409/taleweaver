"""A causal link can refer only to a confirmed fact in the emitted projection."""

from backend.engine.scene_continuity.ledger import read
from backend.engine.scene_continuity.presentation import project as project_continuity
from tests.test_scene_continuity import apply_to, message, state, update


def test_projected_cause_identifiers_refer_to_included_confirmed_facts():
    environment = update(
        key="room",
        kind="environment",
        subject_id="LAB",
        source="scene_description",
        detail="Brass ceiling lamps illuminate the room.",
        visual_detail="Warm lamps",
        evidence="Cobalt mosaic walls and warm brass ceiling lamps.",
    )
    saved, errors = apply_to(updates=[environment])
    assert not errors
    cause = next(iter(read(saved).records))
    saved, errors = apply_to(
        saved,
        [
            update(
                key="warmth",
                kind="effect",
                subject_id="LAB",
                detail="The lamp has warmed the room.",
                cause_id=cause,
                evidence="The lamp has warmed the room.",
            )
        ],
        reply=message("effect", "The lamp has warmed the room."),
    )
    assert not errors
    view = project_continuity(state(saved), scene_description="Changed authored lighting.")
    included = {row["id"] for row in view["facts"]}
    assert cause not in included
    assert all(not row.get("cause_id") or row["cause_id"] in included for row in view["facts"])


def test_budget_omission_does_not_leave_a_dangling_cause_pointer():
    import json

    from backend.engine.scene_continuity.schema import KEY

    saved, errors = apply_to(updates=[update(key="lamp", kind="environment", subject_id="LAB")])
    assert not errors
    cause = next(iter(read(saved).records))
    saved, errors = apply_to(
        saved, [update(key="warmth", kind="effect", cause_id=cause)], reply=message("effect")
    )
    assert not errors
    ledger = read(saved)
    assert len(ledger.records) == 2
    effect = next(row for row in ledger.records.values() if row.kind == "effect")
    for index in range(30):
        row = effect.model_copy(
            deep=True,
            update={"id": f"effect-{index}", "key": f"effect-{index}", "detail": "D" * 400},
        )
        ledger.records[row.id] = row
    view = project_continuity(state({**saved, KEY: ledger.model_dump()}))
    included = {row["id"] for row in view["facts"]}
    assert view["omitted"] > 0 and cause not in included
    assert len(json.dumps(view["facts"], ensure_ascii=False)) <= 10000
    assert all(not row.get("cause_id") or row["cause_id"] in included for row in view["facts"])


def test_confirmation_due_cause_is_visible_without_a_confirmed_causal_link():
    saved, errors = apply_to(updates=[update(review_after_minutes=1)])
    assert not errors
    cause = next(iter(read(saved).records))
    saved, errors = apply_to(
        saved, [update(key="fog", kind="effect", cause_id=cause)], reply=message("effect")
    )
    assert not errors
    view = project_continuity(state(saved, minute=12))
    by_id = {row["id"]: row for row in view["facts"]}
    assert len(by_id) == 2
    assert by_id[cause]["status"] == "needs_confirmation"
    assert all(not row.get("cause_id") for row in view["facts"])
