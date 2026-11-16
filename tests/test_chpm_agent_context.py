"""Retrieved factual content reaches both narrator and reviewer, with observer provenance."""

import pytest

from backend.engine.chpm import agent_context, rendering, runtime
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.host_state import record
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import KernelState
from tests.test_chpm_host_state import mind, source
from tests.test_chpm_kernel import decision, observation


def prepared():
    value = record(
        mind(), source("old", "The cobalt compass is in the amber locker; code 7319."), minute=1
    )
    tools = Tools(value, observation(), {})
    tools.search("compass")
    chosen = decision()
    chosen.agent_evidence = agent_context.collect(tools.pins, observation())
    turn = runtime.Turn(KernelState(), "input", decisions={"npc": chosen}, minds={"npc": value})
    return turn, chosen, value


def test_facts_reach_narration_and_review_even_if_not_chosen_as_a_motive():
    turn, chosen, _ = prepared()
    assert not chosen.candidate_motives
    assert "7319" in runtime.contract(turn)
    review = rendering._review_payload(turn, {}, "")
    evidence = review["contract"]["npc"]["agent_observed_sources"][0]
    assert evidence["text"] == "The cobalt compass is in the amber locker; code 7319."
    assert evidence["source_message_id"] == "old" and not evidence["current_turn"]
    assert evidence["kind"] == "reported"


@pytest.mark.parametrize("change", ["missing", "text", "session", "observer"])
def test_handoff_rejects_stale_or_foreign_sources(change):
    _, chosen, value = prepared()
    if change == "missing":
        value = mind()
    elif change == "text":
        chosen.agent_evidence[0].text = "Invented location and code 4209."
    elif change == "session":
        value = mind(session="other-session")
    else:
        value = mind(actor="someone-else")
    with pytest.raises(ChpmError):
        agent_context.present(chosen, value)
