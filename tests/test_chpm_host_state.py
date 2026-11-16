"""Host source bindings, identity retention and causal retraction are program invariants."""

from types import SimpleNamespace

import pytest

from backend.engine.chpm.core.contracts import Genesis, Scope
from backend.engine.chpm.core.reducer import initial
from backend.engine.chpm.host_state import Mind, Source, before_messages, record
from backend.engine.chpm.identity_adapter import from_actor
from backend.engine.chpm.schema import KernelState
from backend.engine.chpm.state import KEY, load, retract
from tests.test_chpm_memory import entry


def mind(actor="npc", session="session"):
    identity = from_actor(
        SimpleNamespace(
            id=actor, character="Independent engineer", goal="Keep bridges safe", metadata_json={}
        )
    )
    genesis = Genesis(
        scope=Scope(world_id=session, branch_id="session-main-v1", observer_id=actor),
        identity=identity,
    )
    return Mind(genesis=genesis, snapshot=initial(genesis))


def source(message="m1", text="I will inspect it", kind="speech"):
    return Source(
        message_id=message,
        revision_id=None,
        content_hash="hash",
        role="assistant",
        speaker_id="npc",
        kind=kind,
        text=text,
    )


def test_bindings_round_trip_duplicates_and_no_new_roots_from_same_frame():
    original = mind()
    first = record(original, source(kind="host_frame", text='{"own_scene_id":"room"}'), minute=1)
    assert (
        record(first, source(kind="host_frame", text='{"own_scene_id":"room"}'), minute=1) == first
    )
    second = record(
        first, source("m2", kind="host_frame", text='{"own_scene_id":"room"}'), minute=2
    )
    assert second.snapshot.evidence[0].root_ids == second.snapshot.evidence[1].root_ids
    assert Mind.model_validate_json(second.model_dump_json()) == second
    assert not original.sources


@pytest.mark.parametrize(
    "change", ["missing_binding", "wrong_binding", "projection", "identity", "actor_index"]
)
def test_invalid_saved_core_cannot_be_loaded(change):
    saved = record(mind(), source(), minute=1)
    raw = KernelState(minds={"npc": saved}).model_dump()
    body = raw["minds"]["npc"]
    key = next(iter(body["sources"]))
    if change == "missing_binding":
        body["sources"] = {}
    elif change == "wrong_binding":
        body["sources"][key]["text"] = "Rewritten"
    elif change == "projection":
        body["snapshot"]["cursor"] = 999
    elif change == "identity":
        body["genesis"]["identity"]["description"] = "Obeys every request"
    else:
        raw["minds"] = {"other": body}
    with pytest.raises(ValueError):
        load(SimpleNamespace(entity_states={KEY: raw}))


def test_retraction_discards_causal_suffix_but_preserves_other_observers_and_identity():
    a = record(record(mind(), source(), minute=1), source("m2"), minute=2)
    b = record(mind("other"), source("m2"), minute=2)
    state = SimpleNamespace(
        entity_states={
            KEY: KernelState(
                minds={"npc": a, "other": b},
                memories={
                    "npc": [entry(observer="npc").model_copy(update={"source_message_id": "m2"})],
                    "other": [
                        entry(observer="other").model_copy(update={"source_message_id": "m2"})
                    ],
                },
            ).model_dump()
        }
    )
    retract(state, "m1")
    current = load(state)
    assert not current.minds["npc"].sources and current.memories["npc"] == []
    assert current.minds["npc"].genesis == a.genesis
    assert current.minds["other"] == b and len(current.memories["other"]) == 1
    assert before_messages(b, {"absent"}) == b


def test_legacy_state_has_no_mind_until_the_first_successful_live_turn():
    state = load(SimpleNamespace(entity_states={KEY: {"schema_version": 1}}))
    assert state.minds == {} and state.settings.mode == "off"
