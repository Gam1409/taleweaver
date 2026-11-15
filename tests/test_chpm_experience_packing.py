"""Stored reasons fill available narrator space without changing admitted experience."""

from copy import deepcopy

import pytest

from backend.engine.chpm import appraisal_context, experience, motivation, narrative_context
from backend.engine.chpm.host_state import Mind
from tests.test_chpm_appraisal import heard
from tests.test_chpm_experience import proposed


def with_reasons(reasons: tuple[str, ...]) -> Mind:
    dimensions = (
        ("affect", "fear"),
        ("affect", "anger"),
        ("need_frustration", "autonomy"),
        ("need_frustration", "relatedness"),
    )
    value = None
    for index, (reason, (channel, dimension)) in enumerate(zip(reasons, dimensions, strict=False)):
        message = f"packing-{index}"
        text = f"The inspector reported update {index}."
        value = heard(value, message=message, text=text)
        window = appraisal_context.build(value, current_message_id=message)
        alias = next(
            key for key, (_, source, _) in window.sources.items() if source.message_id == message
        )
        estimate = proposed(
            channel=channel,
            dimension=dimension,
            about_id="@player" if channel == "affect" else None,
            citations=[{"source_id": alias, "quote": text}],
            explanation=reason,
        )
        value, _ = experience.accept(
            value,
            [estimate],
            window,
            motivation.build(value, [], window),
            message_id=message,
        )
    assert value is not None
    return value


@pytest.mark.parametrize("short_reason", ["The unresolved promise matters.", "Обещание ещё важно."])
def test_backfills_a_shorter_reason_when_an_earlier_candidate_does_not_fit(short_reason):
    value = with_reasons(('"' * 180, "\\" * 180, short_reason))
    before = value.model_dump_json()
    technical = experience.view(value)
    original = deepcopy(technical)

    packed = narrative_context.experience_reasons(value, technical)

    admitted = {
        row["dimension"]: row["last_assessed_reason"]
        for row in packed["states"]
        if "last_assessed_reason" in row
    }
    assert admitted == {"anger": "\\" * 180, "autonomy": short_reason}
    assert packed["omitted_reasons"] == 1
    assert narrative_context._size(packed) - narrative_context._size(technical) <= 512
    assert value.model_dump_json() == before
    assert technical == original


def test_backfill_stops_at_two_admitted_reasons_in_existing_priority_order():
    value = with_reasons(('"' * 180, "\\" * 180, "First available need.", "Another need."))
    packed = narrative_context.experience_reasons(value, experience.view(value))
    admitted = [row["dimension"] for row in packed["states"] if "last_assessed_reason" in row]
    assert admitted == ["relatedness", "anger"]
    assert packed["omitted_reasons"] == 2


@pytest.mark.parametrize("delta", [0, -1])
def test_backfilled_reason_obeys_exact_serialized_budget(monkeypatch, delta):
    value = with_reasons(('"' * 180, "\\" * 180, "A short reason."))
    technical = experience.view(value)
    expected = {**technical, "states": [dict(row) for row in technical["states"]]}
    expected["omitted_reasons"] = 1
    for row in expected["states"]:
        if row["dimension"] == "anger":
            row["last_assessed_reason"] = "\\" * 180
        if row["dimension"] == "autonomy":
            row["last_assessed_reason"] = "A short reason."
    allowance = narrative_context._size(expected) - narrative_context._size(technical) + delta
    monkeypatch.setattr(narrative_context, "EXPERIENCE_REASON_EXTRA_CHARS", allowance)

    packed = narrative_context.experience_reasons(value, technical)

    admitted = [row for row in packed["states"] if "last_assessed_reason" in row]
    assert len(admitted) == (2 if delta == 0 else 1)
    assert packed["omitted_reasons"] == 3 - len(admitted)
    assert narrative_context._size(packed) - narrative_context._size(technical) <= allowance


def test_ordinary_reasons_keep_the_existing_two_affect_priorities():
    value = with_reasons(
        ("A warning matters.", "An obstruction matters.", "An unmet need matters.")
    )
    packed = narrative_context.experience_reasons(value, experience.view(value))
    admitted = [row["dimension"] for row in packed["states"] if "last_assessed_reason" in row]
    assert admitted == ["anger", "fear"]
    assert packed["omitted_reasons"] == 1
