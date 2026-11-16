"""Optional belief reads preserve subjectivity, source locality and the call budget."""

import json
from types import SimpleNamespace

import pytest

from backend.engine.chpm import agent_context, appraisal, appraisal_context, cognition, motivation
from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.agent_tools import MAX_PINNED_CHARS, Tools
from backend.engine.chpm.host_state import before_messages, record
from backend.engine.chpm.schema import Settings, Usage
from tests.test_chpm_appraisal import accept, heard, proposal
from tests.test_chpm_host_state import mind, source
from tests.test_chpm_kernel import observation, wire_proposal


def inspect(tools, actor="@player"):
    return tools.execute(Lookup(tool="inspect_beliefs", argument=actor))


def basis(tools, alias="ab1"):
    return tools.execute(Lookup(tool="read_belief_basis", argument=alias))


def changed_belief():
    value = accept(heard(), [proposal()])
    value = heard(value, "m2", "An emergency delayed me")
    return accept(
        value,
        [
            proposal(
                belief_id="b1",
                stance="challenge",
                citations=[{"source_id": "e2", "quote": "emergency delayed me"}],
            )
        ],
        "m2",
    )


def test_belief_reads_return_exact_support_and_challenge_without_mutation():
    value = changed_belief()
    original = value.model_dump_json()
    tools = Tools(value, observation(), {})
    result = inspect(tools)
    assert result["results"][0]["status"] == "challenged"
    assert result["results"][0]["subjective"]
    result = basis(tools)
    assert [entry["stance_toward_statement"] for entry in result["results"]] == [
        "support",
        "challenge",
    ]
    assert [entry["results"][0]["text"] for entry in result["results"]] == [
        "missed my promise",
        "emergency delayed me",
    ]
    assert all(entry["results"][0]["kind"] == "reported" for entry in result["results"])
    assert value.model_dump_json() == original
    passed = agent_context.collect(tools.pins, observation())
    assert all(item.kind == "reported" and not item.current_turn for item in passed)
    assert all("Promises may be unreliable" not in item.text for item in passed)


@pytest.mark.parametrize("foreign", [mind(actor="other"), mind(session="other")])
def test_beliefs_cannot_be_read_from_another_observer_or_session(foreign):
    local = Tools(changed_belief(), observation(), {})
    inspect(local)
    other = Tools(foreign, observation(session_id=foreign.genesis.scope.world_id), {})
    assert basis(other) == {"status": "unavailable_belief"}
    assert inspect(other)["results"] == []
    assert not other.pins and not other.beliefs


def test_unexposed_and_retracted_handles_have_no_authority():
    tools = Tools(changed_belief(), observation(), {})
    canonical_id = tools.mind.snapshot.beliefs[0].id
    assert basis(tools, canonical_id) == {"status": "unavailable_belief"}
    inspect(tools)
    tools.mind = before_messages(tools.mind, {"m1"})
    assert basis(tools) == {"status": "unavailable_belief"}
    window = appraisal_context.build(tools.mind, pinned_beliefs=tools.beliefs)
    assert not window.beliefs and not tools.pins


def test_inspection_caps_beliefs_and_reports_omissions():
    value = heard()
    for index in range(4):
        value = accept(value, [proposal(statement=f"Expectation {index}")], f"turn{index}")
    tools = Tools(value, observation(), {})
    result = inspect(tools)
    assert len(result["results"]) == 2 and result["omitted_beliefs"] == 2
    assert len(tools.beliefs) == 2 and inspect(tools) == result
    assert inspect(tools, "unknown")["results"] == []
    assert len(json.dumps(result)) < 1000


def test_basis_shares_source_budget_and_keeps_distinct_excerpts_of_same_source():
    tools = Tools(changed_belief(), observation(), {})
    inspect(tools)
    filler = source("filler", "x" * 2000)
    tools.pins = {f"a{i}": (f"record{i}", filler, filler.text) for i in range(3)}
    result = basis(tools)
    assert all(
        row["results"][0]["status"] == "evidence_budget_exhausted" for row in result["results"]
    )
    assert sum(len(item[2]) for item in tools.pins.values()) == MAX_PINNED_CHARS
    tools.pins.clear()
    src = source("both", "first clause; then the second clause")
    tools.expose("both", src, fragment="first clause")
    tools.expose("both", src, fragment="second clause")
    assert tools.pins["a1"][2] == src.text


def test_old_belief_is_pinned_into_revision_and_motive_allowlists():
    value = accept(heard(), [proposal()])
    value = heard(value, "other-turn", "Another person spoke", speaker="other")
    for index in range(10):
        value = accept(
            value,
            [proposal(about_id="other", statement=f"Another expectation {index}")],
            f"b{index}",
        )
    original = next(b for b in value.snapshot.beliefs if b.about_id == "@player")
    # The ordinary eight-belief view has evicted the original proposition.
    assert original.id not in {b.id for b in appraisal_context.build(value).beliefs.values()}
    tools = Tools(value, observation(), {})
    inspect(tools)
    window = appraisal_context.build(value, belief_limit=1, pinned_beliefs=tools.beliefs)
    assert window.beliefs["ab1"] == original
    assert window.identifiers()["belief_id"] == ["b1", "ab1"]
    assert motivation.build(value, [], window).sources["belief-ab1"].status == "tentative"
    changed, _ = appraisal.accept(
        value, [proposal(belief_id="ab1", stance="challenge")], window, message_id="new"
    )
    revised = next(b for b in changed.snapshot.beliefs if b.id == original.id)
    assert revised.status == "challenged"
    assert len(revised.support_roots) == 1


async def test_two_agent_rounds_feed_old_belief_and_exact_basis_into_real_decision():
    value = accept(heard(), [proposal()])
    for index in range(10):
        value = record(value, source(f"filler{index}", f"Routine {index}"), minute=1)
    value = heard(value, "input", "An emergency delayed me")
    calls = []

    class Model:
        max_tokens = 4096
        model = "offline-mock"
        request_timeout = 5

        async def aexecute_simple_task(self, system, content, schema, **kwargs):
            phase = kwargs["phase"]
            payload = json.loads(content)
            calls.append(phase)
            if phase == "agent_lookup":
                request = (
                    {"tool": "read_belief_basis", "argument": "ab1"}
                    if payload["previous_lookups"]
                    else {"tool": "inspect_beliefs", "argument": "@player"}
                )
                return json.dumps({"requests": [request]})
            assert phase == "proposal"
            context = payload["appraisal_context"]
            assert any(b["belief_id"] == "ab1" for b in context["existing_beliefs"])
            assert any(s["text"] == "missed my promise" for s in context["visible_evidence"])
            current = next(s for s in context["visible_evidence"] if s["current_turn"])
            raw = wire_proposal()
            raw["belief_revisions"] = [
                proposal(
                    belief_id="ab1",
                    stance="challenge",
                    citations=[
                        {"source_id": current["source_id"], "quote": "emergency delayed me"}
                    ],
                ).model_dump()
            ]
            return json.dumps(raw)

    host = SimpleNamespace(game_id="session", _chpm_model_factory=lambda role: Model())
    usage = Usage()
    selected, changed = await cognition.deliberate(
        host,
        Settings(mode="live", actor_ids=["npc"], agent_steps=2, max_input_chars=32000),
        usage,
        "npc",
        observation(),
        {},
        [],
        value,
    )
    assert calls == ["agent_lookup", "agent_lookup", "proposal"] and usage.calls == 3
    assert changed.snapshot.beliefs[0].status == "challenged"
    assert changed.genesis == value.genesis
    assert selected.agent_evidence[0].text == "missed my promise"
    assert "text" not in str(selected.agent_audit)
