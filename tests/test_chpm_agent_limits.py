"""Cross-tool limits and persistence must agree before a reviewed turn is saved."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import agent_context, appraisal, appraisal_context, cognition, runtime
from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.appraisal_contracts import Assessment, Revision
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import Decision, KernelState, Settings, Verdict
from backend.engine.chpm.state import load, save
from tests.test_chpm_appraisal import heard
from tests.test_chpm_host_state import mind, source
from tests.test_chpm_kernel import decision, observation, wire_proposal


def sources_and_beliefs():
    value = mind()
    for index in range(8):
        value = heard(value, f"m{index}", f"Evidence fragment {index}.")
    for group in range(2):
        window = appraisal_context.build(value, recent_limit=20)
        aliases = list(window.sources)
        assessment = Assessment(
            about_id="@player",
            domain="reliability",
            statement=f"Proposition {group}",
            stance="support",
            alternatives=[],
            unknowns=[],
            citations=[
                {
                    "source_id": aliases[4 * group + i],
                    "quote": f"Evidence fragment {4 * group + i}.",
                }
                for i in range(2)
            ],
        )
        value, _ = appraisal.accept(value, [assessment], window, message_id=f"belief{group}")
        window = appraisal_context.build(value, recent_limit=20)
        belief_id = next(
            key
            for key, belief in window.beliefs.items()
            if belief.statement == assessment.statement
        )
        revision = Revision(
            belief_id=belief_id,
            stance="challenge",
            alternatives=[],
            unknowns=[],
            citations=[
                {
                    "source_id": aliases[4 * group + i],
                    "quote": f"Evidence fragment {4 * group + i}.",
                }
                for i in (2, 3)
            ],
        )
        value, _ = appraisal.accept(value, [revision], window, message_id=f"revision{group}")
    return heard(heard(value, "extra1", "Unrelated zeta one."), "extra2", "Unrelated zeta two.")


def read_four_tools(tools):
    inspected = tools.execute(Lookup(tool="inspect_beliefs", argument="@player"))
    search = tools.execute(Lookup(tool="search_memory", argument="zeta"))
    bases = [
        tools.execute(Lookup(tool="read_belief_basis", argument=row["belief_id"]))
        for row in inspected["results"]
    ]
    return search, bases


def test_four_legal_reads_report_overflow_and_leave_saved_history_readable():
    value = sources_and_beliefs()
    tools = Tools(value, observation(), {})
    _, bases = read_four_tools(tools)
    denied = [
        citation
        for basis in bases
        for grounds in basis["results"]
        for citation in grounds["results"]
        if citation["status"] != "ok"
    ]
    assert denied == [{"status": "evidence_source_limit_reached"}] * 2
    assert [row["status"] for row in bases] == ["ok", "partial"]
    assert len(tools.pins) == 8
    assert len(tools.exposed) == 8
    assert tools.mind == value  # Reading never deletes historical evidence to fit the view.
    chosen = decision()
    chosen.agent_evidence = agent_context.collect(tools.pins, observation())
    state = KernelState(actors={"npc": chosen}, minds={"npc": value})
    host = SimpleNamespace(entity_states={"other": {"hp": 8}})
    save(host, state, expected_revision=0)
    restored = load(host)
    assert len(restored.actors["npc"].agent_evidence) == 8
    assert restored.minds["npc"] == value
    assert host.entity_states["other"] == {"hp": 8}
    assert state.revision == 0 and restored.revision == 1


def test_full_source_can_still_be_read_when_the_count_limit_is_reached():
    tools = Tools(mind(), observation(), {})
    for index in range(8):
        tools.expose(
            str(index), source(str(index), "first clause; second clause"), fragment="first clause"
        )
    denied = tools.expose("ninth", source("ninth", "No room"))
    assert denied == {"status": "evidence_source_limit_reached"}
    result = tools.execute(Lookup(tool="read_memory", argument="0"))
    assert result["text"] == "first clause; second clause"
    assert len(tools.pins) == 8
    assert tools.execute(Lookup(tool="read_memory", argument="ninth")) == {
        "status": "unavailable_source"
    }


def test_separate_quotes_keep_their_contiguous_context_without_expanding_to_full_source():
    tools = Tools(mind(), observation(), {})
    for index in range(5):
        text = f"Other source {index}. " + "x" * 1080
        assert tools.expose(str(index), source(str(index), text), full=True)["status"] == "ok"
    text = "p" * 600 + "first quotation; " + "context " * 10 + "second quotation" + "s" * 800
    item = source("target", text)
    first = tools.expose("target", item, fragment="first quotation")
    second = tools.expose("target", item, fragment="second quotation")
    assert second["status"] == "ok"
    assert second["source_id"] == first["source_id"]
    assert second["text"] == "first quotation; " + "context " * 10 + "second quotation"
    assert second["text"] in item.text
    assert len(tools.pins) == 6
    assert tools.execute(Lookup(tool="read_memory", argument="target")) == {
        "status": "evidence_budget_exhausted"
    }
    assert tools.pins[first["source_id"]][2] == second["text"]


@pytest.mark.parametrize("invalid", ["count", "characters", "duplicate"])
def test_handoff_rejects_invalid_batches_even_if_a_producer_bypasses_tools(invalid):
    entries = 9 if invalid == "count" else 4 if invalid == "characters" else 2
    text = "x" * 1600 if invalid == "characters" else "quote"
    pins = {
        f"a{i}": ("same" if invalid == "duplicate" else str(i), source(str(i), text), text)
        for i in range(entries)
    }
    with pytest.raises(ChpmError):
        agent_context.collect(pins, observation())


@pytest.mark.parametrize("invalid", ["count", "text", "scope", "trace"])
def test_invalid_mutated_state_is_rejected_before_replacing_entity_states(invalid):
    host = SimpleNamespace(entity_states={"other": {"hp": 8}})
    save(host, KernelState(actors={"npc": decision()}), expected_revision=0)
    before = deepcopy(host.entity_states)
    value = load(host)
    if invalid == "scope":
        value.minds["wrong-key"] = mind()
    elif invalid == "trace":
        value.actors["npc"].candidate_motives = {"CONTINUE": []}
    else:
        evidence = agent_context.collect(
            {"a1": ("one", source(), "I will inspect it")}, observation()
        )[0]
        if invalid == "text":
            evidence.text = "x" * 2001
        value.actors["npc"].agent_evidence = [evidence] * (9 if invalid == "count" else 1)
    with pytest.raises(ChpmError, match="invalid"):
        save(host, value, expected_revision=1)
    assert host.entity_states == before
    assert load(host).revision == 1
    assert value.revision == 1


async def test_two_round_cognition_reviewed_finish_and_fresh_reload_preserve_limits():
    value = sources_and_beliefs()
    settings = Settings(mode="live", actor_ids=["npc"], agent_steps=2, max_input_chars=32000)
    initial = KernelState(settings=settings)
    state = SimpleNamespace(
        entity_states={"__chpm__": initial.model_dump()},
        in_game_time=value.snapshot.sim_minute,
    )
    calls = []

    class Model:
        model = "offline-mock"
        max_tokens = 4096
        request_timeout = 5

        async def aexecute_simple_task(self, system, content, model, **kwargs):
            calls.append(kwargs["phase"])
            supplied = json.loads(content)
            if kwargs["phase"] != "agent_lookup":
                assert supplied["agent_lookup_status"][-1] == {
                    "tool": "read_belief_basis",
                    "status": "partial",
                }
                return json.dumps(wire_proposal())
            requests = (
                [
                    {"tool": "inspect_beliefs", "argument": "@player"},
                    {"tool": "search_memory", "argument": "zeta"},
                ]
                if not supplied["previous_lookups"]
                else [
                    {"tool": "read_belief_basis", "argument": "ab1"},
                    {"tool": "read_belief_basis", "argument": "ab2"},
                ]
            )
            return json.dumps({"requests": requests})

    host = SimpleNamespace(game_id="session", state=state, _chpm_model_factory=lambda role: Model())
    turn = runtime.Turn(initial, "input", names={"npc": "NPC"}, present_names={"npc": "NPC"})
    host._chpm_turn = turn
    chosen, changed = await cognition.deliberate(
        host, settings, turn.usage, "npc", observation(), {}, [], value
    )
    assert calls == ["agent_lookup", "agent_lookup", "proposal"]
    assert len(chosen.agent_evidence) == 8
    assert Decision.model_validate_json(chosen.model_dump_json()) == chosen
    turn.decisions["npc"], turn.minds["npc"] = chosen, changed
    text = "I will discuss the checks."
    turn.verdict = Verdict(matches=True, evidence=[{"actor_id": "npc", "quote": text}])
    reply = SimpleNamespace(
        id="reply",
        session_id="session",
        role="assistant",
        scene_id="room",
        revision_id=None,
        content=text,
    )
    runtime.finish(host, reply, completed=True)
    # A new host reading JSON, rather than an already-instantiated Pydantic model.
    fresh = load(SimpleNamespace(entity_states=json.loads(json.dumps(state.entity_states))))
    assert fresh.actors["npc"].status == "delivered"
    assert len(fresh.actors["npc"].agent_evidence) == 8
    assert set(value.sources) <= set(fresh.minds["npc"].sources)
    assert "evidence_source_limit_reached" in str(fresh.actors["npc"].agent_audit)
    assert fresh.usage.calls == 3 and not fresh.usage.proposal_repairs
