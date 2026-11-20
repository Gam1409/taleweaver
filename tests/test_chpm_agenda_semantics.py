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
from tests.test_chpm_json_schema_references import resolved
from tests.test_chpm_kernel import observation, wire_proposal
from tests.test_chpm_runtime import prepared


@pytest.mark.parametrize("schema", [CandidateBody, Draft])
def test_offered_proposal_schema_explains_spoken_agenda_and_null_for_current_actions(schema):
    contract = json_contract.response_schema(schema, {}, explicit_keys=True)
    intent = contract["$defs"]["AgendaIntent"]
    from backend.engine.chpm.agenda_semantics import GLOSSARY

    assert "spoken" in intent["description"].lower()
    assert "AGENDA CODES" in intent["description"]
    for meaning in (
        "null=immediate/ordered acts, silent/private intent",
        "goal=ongoing aim",
        "commitment=ongoing undertaking",
        "withdraw=cancel",
        "report_done=claim done, not world fact",
        "text=ACTIVE OWNED TEXT, not dialogue",
        "entry_id=ACTIVE ID",
    ):
        assert meaning in GLOSSARY
    assert GLOSSARY in prompts.PROPOSE
    fields = contract.get("$defs", {}).get("Intent", contract)["properties"]
    assert fields["agenda_change"]["default"] is None
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
    parameters = offered[0]["function"]["parameters"]
    candidates = resolved(parameters, parameters["properties"]["candidates"])
    native = candidates["properties"]["CONTINUE"]["properties"]["agenda_change"]["anyOf"][0]
    system, content = compose(
        [{"role": "system", "content": prompts.PROPOSE}, {"role": "user", "content": "{}"}],
        offered,
    )
    assert GLOSSARY in system
    payload = json.loads(content)
    assert payload["functions"][0]["name"] == "submit_decision"
    assert native["description"] in content
    assert "No promise wording required" not in system


def test_field_edit_repair_keeps_the_shared_meanings_and_explicit_unique_paths():
    from backend.engine.chpm.agenda_semantics import GLOSSARY
    from backend.engine.chpm.proposal_repair import Prepared

    instruction = Prepared({}, {}, original=wire_proposal()).instruction(prompts.PROPOSE)

    assert instruction.count(GLOSSARY) == 1
    assert "Use each allowed path once" in instruction
    assert "one full parent/array replacement" in instruction


def test_only_the_producer_needs_the_new_entry_admission_flag():
    assert "agenda_creation_available" in prompts.PROPOSE
    for instruction in (prompts.NARRATE, prompts.VERIFY, narration_repair_input.CONTRACT_RULES):
        assert "agenda_creation_available" not in instruction


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
    assert GLOSSARY in prompts.VERIFY
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
