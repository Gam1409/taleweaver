"""Archive rollover preserves provenance, derived state and lifecycle operations."""

import pytest

from backend.engine.chpm import appraisal_context, lifecycle
from backend.engine.chpm.core import reducer
from backend.engine.chpm.core.contracts import Citation, Event, Interpret
from backend.engine.chpm.core.history import events
from backend.engine.chpm.core.replay import restore, rewind
from backend.engine.chpm.host_state import Mind, before_messages, record
from backend.engine.chpm.schema import KernelState
from backend.engine.chpm.state import KEY
from tests.test_chpm_capacity import filled
from tests.test_chpm_host_state import mind, source


@pytest.fixture(scope="module")
def long_mind():
    return filled(720)


def test_over_old_capacity_is_lossless_and_round_trips(long_mind):
    snapshot = long_mind.snapshot
    assert len(snapshot.journal) <= 256
    assert len(snapshot.archive) == 4
    assert len(events(snapshot)) == len(long_mind.sources) == 720
    assert Mind.model_validate_json(long_mind.model_dump_json()) == long_mind
    first = events(snapshot)[0]
    assert reducer.apply(snapshot, first, expected_revision=0).duplicate
    with pytest.raises(ValueError, match="reused"):
        reducer.apply(snapshot, first.model_copy(update={"sim_minute": 99}), expected_revision=0)


def test_archived_source_still_supports_interpretation_without_new_root(long_mind):
    first = long_mind.snapshot.evidence[0]
    body = Interpret(
        record_id="late-interpretation",
        belief_id="promise",
        about_id="@player",
        domain="reliability",
        statement="A tentative interpretation",
        stance="support",
        citations=(Citation(record_id=first.id, quote=first.text),),
    )
    event = Event(
        scope=long_mind.genesis.scope,
        event_id="late-interpretation",
        sequence=721,
        sim_minute=721,
        payload=body,
    )
    result = reducer.apply(long_mind.snapshot, event, expected_revision=720).snapshot
    assert result.beliefs[0].support_roots == first.root_ids
    assert restore(result.model_dump(), expected_genesis=long_mind.genesis) == result
    assert rewind(result, through_sequence=720) == long_mind.snapshot


def test_archive_corruption_and_finite_capacity_reject_without_mutation(long_mind, monkeypatch):
    raw = long_mind.model_dump()
    raw["snapshot"]["archive"][0]["events"][0]["payload"]["text"] = "Changed past"
    with pytest.raises(ValueError):
        Mind.model_validate(raw)
    monkeypatch.setattr(reducer, "MAX_EVENTS", 720)
    with pytest.raises(ValueError, match="capacity"):
        record(long_mind, source("overflow"), minute=721)
    assert len(events(long_mind.snapshot)) == 720


def test_retraction_and_fork_cross_archive_boundary(long_mind):
    shorter = before_messages(long_mind, {"m130"})
    assert len(events(shorter.snapshot)) == len(shorter.sources) == 130
    assert not shorter.snapshot.archive
    assert shorter.genesis == long_mind.genesis
    mapping = {f"m{i}": f"copy-{i}" for i in range(720)}
    copied = lifecycle.fork(
        {KEY: KernelState(minds={"npc": long_mind}).model_dump()}, mapping, "copy"
    )
    result = KernelState.model_validate(copied[KEY]).minds["npc"]
    assert len(events(result.snapshot)) == 720
    assert result.genesis.identity == long_mind.genesis.identity
    assert {s.message_id for s in result.sources.values()} == set(mapping.values())
    assert not set(result.sources) & set(long_mind.sources)


def test_legacy_snapshot_migrates_only_layout_and_preserves_hashes():
    original = filled(400)
    raw = original.model_dump()
    raw["snapshot"]["schema_version"] = 1
    raw["snapshot"]["journal"] = [event.model_dump() for event in events(original.snapshot)]
    del raw["snapshot"]["archive"]
    for value in raw["sources"].values():
        value.pop("facts")
    assert Mind.model_validate(raw) == original


def test_episodic_recall_is_bounded_exact_and_retractable():
    value = mind()
    for number in range(40):
        text = (
            "Я помню обсерваторию: встреча сорвалась."
            if number == 2
            else f"Обычный разговор {number}"
        )
        value = record(value, source(f"m{number}", text=text), minute=number)
    before = value.model_dump_json()
    recalled = appraisal_context.build(value, query="Расскажи про обсерваторию")
    old = recalled.sources["r1"]
    assert old[1].message_id == "m2" and old[2] in old[1].text
    assert recalled.payload["episodic_recall"]["new_evidence"] is False
    assert recalled.payload["episodic_recall"]["recalled_sources"] == 1
    assert recalled.payload["evidence_omitted"] == 33
    assert appraisal_context.build(value, query="другое").payload["recollected_episodes"] == []
    assert appraisal_context.build(value, query="Расскажи про обсерваторию") == recalled
    assert value.model_dump_json() == before
    changed = before_messages(value, {"m2"})
    assert not appraisal_context.build(changed, query="обсерваторию").payload[
        "recollected_episodes"
    ]


def test_recall_limits_fragments_and_reports_omitted_matches():
    value = mind()
    for number in range(40):
        text = (
            "start " + "word " * 230 + "observatory " + "tail " * 100
            if number < 10
            else f"routine {number}"
        )
        value = record(value, source(f"m{number}", text=text), minute=number)
    window = appraisal_context.build(value, query="observatory")
    recalled = [row for alias, row in window.sources.items() if alias.startswith("r")]
    assert len(recalled) == 3
    assert all(
        len(text) <= 300 and text in origin.text and "observatory" in text
        for _, origin, text in recalled
    )
    assert window.payload["episodic_recall"]["omitted_matches"] == 7
