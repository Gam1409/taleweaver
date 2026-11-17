"""Declared agenda meanings reach every model without changing action-only delivery."""

import json
from types import SimpleNamespace

import pytest

from backend.engine.chpm import (
    inference,
    integrated_request,
    json_contract,
    narration_repair_input,
    prompts,
    rendering,
    runtime,
)
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.json_tool_port import compose
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import AgendaIntent, CandidateBody
from backend.engine.chpm.state import load
from tests.test_chpm_action_expression import TEXT, reply, review
from tests.test_chpm_host_state import mind
from tests.test_chpm_kernel import observation, wire_proposal
from tests.test_chpm_runtime import prepared


@pytest.mark.parametrize("schema", [CandidateBody, Draft])
def test_offered_proposal_schema_explains_spoken_agenda_and_null_for_current_actions(schema):
    contract = json_contract.response_schema(schema, {}, explicit_keys=True)
    intent = contract["$defs"]["AgendaIntent"]
    assert "spoken" in intent["description"]
    statuses = intent["properties"]["action"]["description"]
    for label in (
        "Declared ongoing goal",
        "Spoken ongoing commitment",
        "Spoken withdrawal",
        "Spoken completion claim",
    ):
        assert label in statuses
    fields = contract.get("$defs", {}).get("Intent", contract)["properties"]
    assert "null" in fields["agenda_change"]["description"]
    assert "silent" in fields["agenda_change"]["description"]
    assert intent["properties"]["action"]["enum"] == [
        "goal",
        "commitment",
        "withdraw",
        "report_done",
    ]


def test_native_submission_and_portable_catalog_preserve_the_same_agenda_definitions():
    from backend.engine.chpm.agenda_semantics import GLOSSARY

    value = SimpleNamespace(schema=Draft, identifiers={})
    tools = Tools(mind(), observation(), {})
    offered = integrated_request._definitions(value, tools, 0)
    native = offered[0]["function"]["parameters"]["$defs"]["AgendaIntent"]
    system, content = compose(
        [{"role": "system", "content": prompts.PROPOSE}, {"role": "user", "content": "{}"}],
        offered,
    )
    assert GLOSSARY in system
    payload = json.loads(content)
    assert payload["functions"][0]["name"] == "submit_decision"
    assert native["properties"]["action"]["description"] in content
    assert "No promise wording required" not in system


@pytest.mark.parametrize("embedded", [False, True])
def test_narration_and_both_repair_paths_receive_one_shared_glossary(embedded):
    from backend.engine.chpm.agenda_semantics import GLOSSARY

    host = prepared()
    turn = host._chpm_turn
    original = runtime.contract(turn) if embedded else "Original narration policy."
    system, content = narration_repair_input.build(
        turn,
        original,
        TEXT,
        "",
        ["Missing spoken undertaking"],
        portrait_reminder="Portrait policy",
    )
    assert GLOSSARY in runtime.contract(turn)
    assert system.count(GLOSSARY) == 1
    assert "Spoken ongoing commitment" in prompts.VERIFY
    payload = json.loads(content)
    if not embedded:
        assert payload["dialogue_contract"] == runtime.contract_data(turn)
    assert turn.decisions["npc"].selected.agenda_change is None


async def test_actual_reviewer_receives_shared_meanings_and_accepts_silent_action_only(monkeypatch):
    from backend.engine.chpm.agenda_semantics import GLOSSARY

    host = prepared()
    host._chpm_turn.decisions["npc"].selected.intention = "Fold my map and place it on the table."
    requests = []

    async def request(_manager, _settings, _usage, instruction, payload, *_args, **_kwargs):
        requests.append((instruction, payload))
        assert GLOSSARY in instruction
        assert payload["contract"]["npc"]["agenda_change"] is None
        return review()

    monkeypatch.setattr(inference, "request", request)
    assert (
        await rendering.validate(host, TEXT, completed=True, resolution="", system_prompt="Policy")
        == TEXT
    )
    runtime.finish(host, reply(), completed=True)
    saved = load(host.state)
    assert len(requests) == 1 and saved.agenda == []
    assert saved.actors["npc"].spoken_evidence == ""
    assert saved.actors["npc"].action_evidence == TEXT


def test_existing_agenda_values_and_proposals_keep_their_serialized_wire_contract():
    for action in ("goal", "commitment", "withdraw", "report_done"):
        value = {
            "action": action,
            "text": "Repair the bridge",
            "entry_id": "owned" if action in {"withdraw", "report_done"} else None,
        }
        assert AgendaIntent.model_validate_json(json.dumps(value)).model_dump() == value
    value = Draft.model_validate(wire_proposal())
    assert Draft.model_validate_json(value.model_dump_json(by_alias=True)) == value
    assert all(candidate.agenda_change is None for candidate in value.candidates.values())
