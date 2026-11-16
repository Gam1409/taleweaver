"""An unknown subject must not masquerade as an empty observer-local belief read."""

import json
from types import SimpleNamespace

import pytest

from backend.engine.chpm import agent, agent_beliefs, appraisal_context
from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.schema import Settings, Usage
from tests.test_chpm_appraisal import accept, heard, proposal
from tests.test_chpm_host_state import mind
from tests.test_chpm_kernel import observation


async def test_agent_supplies_player_id_and_no_dangling_belief_context_reference():
    value = accept(heard(), [proposal()])
    supplied = {"psychological_state": {"belief_context_ref": "appraisal_context.existing_beliefs"}}
    captured = []

    class Model:
        model = "offline"
        max_tokens = 4096
        request_timeout = 5

        async def aexecute_simple_task(self, system, content, model, **kwargs):
            payload = json.loads(content)
            captured.append(payload)
            return json.dumps(
                {
                    "requests": [
                        {
                            "tool": "inspect_beliefs",
                            "argument": payload.get("player_actor_id", "player"),
                        }
                    ]
                }
            )

    host = SimpleNamespace(game_id="session", _chpm_model_factory=lambda role: Model())
    usage = Usage()
    tools, audit = await agent.investigate(
        host, Settings(agent_steps=1), usage, value, observation(), supplied
    )
    assert captured[0]["player_actor_id"] == "@player"
    assert captured[0]["belief_subject_ids"] == ["@player"]
    assert "belief_context_ref" not in captured[0]["current_state"]
    assert supplied["psychological_state"]["belief_context_ref"]
    assert len(tools.beliefs) == 1 and audit[0]["results"][0]["results"]
    assert usage.calls == 1 and tools.mind == value


@pytest.mark.parametrize("subject", ["player", "unknown", "npc"])
def test_invalid_subject_is_visible_without_guessing_aliases_or_pinning_beliefs(subject):
    value = accept(heard(), [proposal()])
    tools = Tools(value, observation(), {})
    result = tools.execute(Lookup(tool="inspect_beliefs", argument=subject))
    assert result["status"] == "unavailable_subject"
    assert result["results"] == [] and not tools.beliefs and not tools.pins
    assert tools.mind == value


def test_known_subject_without_beliefs_still_returns_a_legitimate_empty_read():
    value = heard(mind(), "peer", "I am here", speaker="other")
    tools = Tools(value, observation(), {})
    for subject in ("@player", "other"):
        assert tools.execute(Lookup(tool="inspect_beliefs", argument=subject)) == {
            "status": "ok",
            "results": [],
            "omitted_beliefs": 0,
        }


def test_subject_view_is_bounded_and_reports_omitted_old_subjects():
    value = mind()
    for index in range(35):
        message, subject, quote = f"m{index}", f"other{index}", f"Claim {index}."
        value = heard(value, message, quote, speaker=subject)
        window = appraisal_context.build(value)
        alias = next(k for k, (_, s, _) in window.sources.items() if s.message_id == message)
        value = accept(
            value,
            [
                proposal(
                    about_id=subject,
                    statement=quote,
                    citations=[{"source_id": alias, "quote": quote}],
                )
            ],
            message,
        )
    original = value.model_dump_json()
    view = agent_beliefs.subject_view(value)
    assert view["player_actor_id"] == "@player"
    assert len(view["belief_subject_ids"]) == 32 and view["omitted_belief_subjects"] == 3
    assert view["belief_subject_ids"][0] == "other34"
    assert value.model_dump_json() == original
