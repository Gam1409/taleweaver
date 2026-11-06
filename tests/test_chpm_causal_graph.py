"""Historical influence edges survive changes to the current causal view."""

from unittest.mock import patch

import pytest

from backend.engine.chpm import causal_graph, causal_memory, host_state, lifecycle
from backend.engine.chpm.causal_audit import MAX_NOTES, add
from backend.engine.chpm.host_state import Mind, before_messages, identifier, record, record_many
from backend.engine.chpm.schema import KernelState, Verdict
from backend.engine.chpm.state import KEY
from tests.test_chpm_causal_memory import TEXT, draft
from tests.test_chpm_compact_contract import contract_fixture
from tests.test_chpm_host_state import mind as empty_mind
from tests.test_chpm_host_state import source as host_source
from tests.test_chpm_memory import source


def graph_opened(*, links=True):
    turn, mind = contract_fixture()
    state = KernelState(minds={"npc": mind})
    body = draft()
    if links:
        body["links"] = [
            {
                "source": "cause",
                "target": "purpose",
                "relation": "motivates",
                "attribution": "inferred",
                "passage_id": "p0",
            },
            {
                "source": "cause",
                "target": "consequence",
                "relation": "causes",
                "attribution": "inferred",
                "passage_id": "p0",
            },
        ]
    reply = source("sample", TEXT)
    turn.verdict = Verdict(matches=True, causal_updates=[body])
    causal_memory.apply(turn, state, reply, {"p0": TEXT})
    return turn, state, reply


def test_source_bound_fact_nodes_and_explicitly_proposed_influence_edges_are_saved():
    _, state, _ = graph_opened()
    records = list(state.minds["npc"].sources.values())
    assert len([s for s in records if s.kind == "causal_fact"]) == 3
    links = [s for s in records if s.kind == "causal_link"]
    assert len(links) == 2
    assert all(link.graph.attribution == "inferred" for link in links)
    assert all(link.facts is None and link.reported for link in links)


def test_merely_recording_events_does_not_invent_a_causal_link():
    _, state, _ = graph_opened(links=False)
    records = list(state.minds["npc"].sources.values())
    assert len([s for s in records if s.kind == "causal_fact"]) == 3
    assert not any(s.kind == "causal_link" for s in records)


def update_thread(turn, state, *, action="update", field="consequence"):
    thread = state.causal_memory.actors["npc"][0]
    turn.causal_threads = {"npc": [thread]}
    reply = source("handover", "Rin handed the sample to the laboratory technician.")
    turn.verdict = Verdict(
        matches=True,
        causal_updates=[
            {
                "actor_id": "npc",
                "action": action,
                "thread_id": thread.id,
                "facts": {field: {"text": "The technician has the sample", "passage_id": "p0"}},
            }
        ],
    )
    causal_memory.apply(turn, state, reply, {"p0": reply.content})
    assert not state.usage.causal_notes
    return reply


def test_new_consequence_preserves_history_and_excludes_obsolete_edges_from_current_view():
    turn, state, _ = graph_opened()
    before = state.minds["npc"]
    update_thread(turn, state)
    mind = state.minds["npc"]
    old = causal_graph.projection(before)
    new = causal_graph.projection(mind)
    assert all(node in new["nodes"] for node in old["nodes"])
    assert new["links"] == old["links"]
    assert new["transitions"][-1]["previous"] == old["transitions"][-1]["id"]
    thread = causal_graph.frontier(mind)[0]
    assert thread.facts["consequence"].text == "The technician has the sample"
    assert [link["target"] for link in causal_graph.current_links(mind, thread)] == ["purpose"]
    assert Mind.model_validate_json(mind.model_dump_json()) == mind


def test_rewinding_completed_event_reopens_prior_state_with_original_circumstances():
    turn, state, _ = graph_opened()
    before = state.causal_memory.actors["npc"][0]
    reply = update_thread(turn, state, action="close")
    assert causal_graph.frontier(state.minds["npc"])[0].closure is not None
    retained = before_messages(state.minds["npc"], {reply.id})
    assert causal_graph.frontier(retained) == [before]
    rebuilt = causal_memory.rebuild(state.causal_memory, {"npc": retained})
    assert rebuilt.actors["npc"] == [before]


def test_saved_json_key_order_cannot_reverse_events_or_break_the_next_transition():
    turn, state, _ = graph_opened()
    update_thread(turn, state)
    original = state.minds["npc"]
    raw = original.model_dump()
    raw["sources"] = dict(reversed(list(raw["sources"].items())))
    restored = Mind.model_validate(raw)
    assert causal_graph.frontier(restored) == causal_graph.frontier(original)
    assert causal_graph.projection(restored) == causal_graph.projection(original)
    thread = causal_graph.frontier(restored)[0]
    assert causal_graph.current_links(restored, thread) == causal_graph.current_links(
        original, thread
    )
    state.minds["npc"] = restored
    update_thread(turn, state, action="close")
    assert causal_graph.frontier(state.minds["npc"])[0].closure is not None


def test_fork_rebinds_graph_endpoints_and_transition_chain_without_changing_identity():
    turn, state, _ = graph_opened()
    update_thread(turn, state)
    cloned = lifecycle.fork(
        {KEY: state.model_dump()}, {"sample": "f-sample", "handover": "f-hand"}, "fork"
    )
    copied = KernelState.model_validate(cloned[KEY]).minds["npc"]
    assert copied.genesis.identity == state.minds["npc"].genesis.identity
    assert copied.genesis.scope.world_id == "fork"
    assert set(copied.sources).isdisjoint(state.minds["npc"].sources)
    assert {s.message_id for s in copied.sources.values()} == {"f-sample", "f-hand"}
    for src in copied.sources.values():
        if src.graph:
            assert set(src.graph.parents) <= copied.sources.keys()
            assert not src.graph.previous or src.graph.previous in copied.sources
    assert (
        causal_graph.frontier(copied)[0].facts["consequence"].text
        == "The technician has the sample"
    )


@pytest.mark.parametrize("case", ["missing", "foreign", "wrong-thread", "future", "chain"])
def test_invalid_graph_dependencies_cannot_be_loaded_or_appended(case):
    turn, state, _ = graph_opened()
    update_thread(turn, state)
    mind = state.minds["npc"]
    edge = next(s for s in mind.sources.values() if s.kind == "causal_link")
    if case == "missing":
        graph = edge.graph.model_copy(update={"parents": ("missing", edge.graph.parents[1])})
    elif case == "foreign":
        edge = edge.model_copy(update={"speaker_id": "someone-else"})
        graph = edge.graph
    elif case == "wrong-thread":
        graph = edge.graph.model_copy(update={"thread_id": "other-thread"})
    elif case == "future":
        future = host_source("later", kind="narration")
        graph = edge.graph.model_copy(
            update={"parents": (identifier(future, mind.genesis), edge.graph.parents[1])}
        )
    else:
        edge = next(s for s in reversed(tuple(mind.sources.values())) if s.kind == "causal_state")
        graph = edge.graph.model_copy(update={"previous": None})
    bad = edge.model_copy(update={"graph": graph, "text": "Tampered relation"})
    additions = [bad, future] if case == "future" else [bad]
    before = mind.model_dump_json()
    with pytest.raises(ValueError):
        record_many(mind, additions, minute=mind.snapshot.sim_minute)
    assert mind.model_dump_json() == before


def test_bad_optional_links_do_not_discard_valid_statements():
    turn, mind = contract_fixture()
    state = KernelState(minds={"npc": mind})
    body = draft()
    body["links"] = [
        None,
        {"source": "event", "target": "purpose", "relation": "causes", "passage_id": "p0"},
        {"source": "cause", "target": "purpose", "relation": "causes", "passage_id": "fabricated"},
    ]
    turn.verdict = Verdict(matches=True, causal_updates=[body])
    causal_memory.apply(turn, state, source("sample", TEXT), {"p0": TEXT})
    assert len(state.causal_memory.actors["npc"]) == 1
    assert len(causal_graph.projection(state.minds["npc"])["nodes"]) == 3
    assert not causal_graph.projection(state.minds["npc"])["links"]
    assert len(state.usage.causal_notes) == 3


def test_graph_projection_failure_does_not_publish_partial_optional_update():
    turn, state, _ = graph_opened()
    before = state.model_dump_json()
    with patch.object(causal_graph, "frontier", side_effect=ValueError("invalid frontier")):
        # No-op retry still validates the entire proposed frontier before installation.
        causal_memory.apply(turn, state, source("sample", TEXT), {"p0": TEXT})
    assert state.minds == KernelState.model_validate_json(before).minds
    assert state.causal_memory == KernelState.model_validate_json(before).causal_memory
    assert "invalid frontier" in state.usage.causal_notes[0]


def test_audit_overflow_counts_omitted_notes_without_failing_an_accepted_turn():
    usage = KernelState().usage
    add(usage, ["Invalid optional link"] * 60)
    assert len(usage.causal_notes) == MAX_NOTES
    assert usage.causal_notes_omitted == 60 - MAX_NOTES


def test_optional_update_without_observer_ledger_cannot_create_a_graphless_record():
    turn, _ = contract_fixture()
    state = KernelState()
    turn.verdict = Verdict(matches=True, causal_updates=[draft()])
    causal_memory.apply(turn, state, source("sample", TEXT), {"p0": TEXT})
    assert not state.causal_memory.actors
    assert not state.minds
    assert "evidence ledger" in state.usage.causal_notes[0]


def test_maximum_update_adds_fourteen_sources_within_reserved_capacity():
    turn, mind = contract_fixture()
    state = KernelState(minds={"npc": mind})
    keys = ["purpose", "cause", "event", "consequence", "next_step"]
    available = {f"p{i}": f"Observed circumstance {i}." for i in range(5)}
    reply = source("max-update", " ".join(available.values()))
    body = {
        "actor_id": "npc",
        "action": "open",
        "facts": {
            key: {"text": available[f"p{i}"], "passage_id": f"p{i}"} for i, key in enumerate(keys)
        },
        "links": [
            {"source": "cause", "target": target, "relation": "enables", "passage_id": "p1"}
            for target in ["purpose", "event", "next_step"]
        ],
    }
    turn.verdict = Verdict(matches=True, causal_updates=[body])
    causal_memory.apply(turn, state, reply, available)
    assert not state.usage.causal_notes
    assert len(state.minds["npc"].sources) - len(mind.sources) == 14
    assert len(causal_graph.projection(state.minds["npc"])["links"]) == 3


def test_causal_view_survives_archiving_and_uses_ledger_order_after_reloading():
    turn, state, _ = graph_opened()
    expected = state.causal_memory.actors["npc"]
    mind = state.minds["npc"]
    mind = record_many(
        mind, [host_source(f"later-{i}") for i in range(300)], minute=mind.snapshot.sim_minute
    )
    assert mind.snapshot.archive
    state.minds["npc"] = Mind.model_validate_json(mind.model_dump_json())
    assert causal_graph.frontier(state.minds["npc"]) == expected
    update_thread(turn, state, action="close")
    assert causal_graph.frontier(state.minds["npc"])[0].closure is not None


def test_atomic_batch_matches_sequential_records_but_validates_once():
    mind = empty_mind()
    additions = [host_source(f"m{index}") for index in range(12)]
    sequential = mind
    for item in additions:
        sequential = record(sequential, item, minute=1)
    with patch.object(host_state, "restore", wraps=host_state.restore) as checked:
        batched = record_many(mind, additions, minute=1)
    assert batched == sequential
    assert checked.call_count == 1
    assert record_many(batched, additions, minute=1) is batched


def test_legacy_source_identifiers_remain_stable_without_optional_graph_field():
    from backend.engine.chpm.host_state import fingerprint

    mind = empty_mind()
    original = host_source()
    body = original.model_dump(exclude={"facts", "graph"})
    legacy_id = fingerprint({"scope": mind.genesis.scope.model_dump(), "source": body})
    assert identifier(original, mind.genesis) == legacy_id
