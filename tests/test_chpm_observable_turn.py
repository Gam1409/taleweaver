"""Current state reads survive the actual decision, narration and reconciliation path."""

import json
from copy import deepcopy

import pytest

from backend.engine.chpm.state import load
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.ledger import apply, read
from backend.models.chat import ChatMessage
from tests.chpm_reference_fixture import proposal as reference_proposal
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_native_notebook_loop import call, turn
from tests.test_chpm_native_notebook_turn import initial_payload, tool_results
from tests.test_chpm_notebook_turn import ACTION, configure, install
from tests.test_chpm_turn import ChpmRoles

DETAIL = "The ring has a shallow scratch."


class StateRoles(ChpmRoles):
    def __init__(self, *, reject=False):
        super().__init__(reject=reject)
        self.lookups, self.reconciliations = [], []

    def for_role(self, *args, **kwargs):
        model = super().for_role(*args, **kwargs)
        model.aexecute_tool_turn = self.native
        return model

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if issubclass(schema, ItemExtraction):
            self.reconciliations.append(json.loads(args[1]))
        return await super().structured(*args, **kwargs)

    async def simple(self, system, payload, model, **kwargs):
        phase = kwargs.get("phase")
        if phase not in {"agent_lookup", "memory_tools", "integrated_decision"}:
            return await super().simple(system, payload, model, **kwargs)
        self.chpm_calls.append(phase)
        body = json.loads(payload)
        self.lookups.append(deepcopy(body))
        assert any(row["id"] == "HIDDEN_RING" for row in body["observable_entities"])
        if not body["previous_lookups"]:
            request = {"name": "inspect_entity", "arguments": {"argument": "HIDDEN_RING"}}
            legacy = {"tool": "inspect_entity", "argument": "HIDDEN_RING"}
            return json.dumps({"requests": [request if "functions" in body else legacy]})
        if phase != "integrated_decision":
            return json.dumps({"requests": []})
        proposal = await self.decision(body, model)
        return json.dumps({"requests": [{"name": "submit_decision", "arguments": proposal}]})

    async def decision(self, body, model):
        result = await ChpmRoles.simple(self, "", json.dumps(body), model, phase="proposal")
        self.chpm_calls.pop()  # Fixture proposal generation is not another model call.
        return reference_proposal(json.loads(result), body)

    async def native(self, messages, tools, model, **kwargs):
        self.chpm_calls.append(kwargs["phase"])
        body = initial_payload(messages)
        self.lookups.append(deepcopy(body))
        assert "inspect_entity" in {row["function"]["name"] for row in tools}
        if not tool_results(messages):
            return turn(call("state-read", "inspect_entity", {"argument": "HIDDEN_RING"}))
        if kwargs["phase"] != "integrated_decision":
            return turn()
        return turn(call("state-decision", "submit_decision", await self.decision(body, model)))


async def prepare(db, workflow, protocol, notebook):
    user, state = await configure(
        db,
        workflow=workflow,
        tool_protocol=protocol,
        notebook_enabled=notebook,
        max_input_chars=48000,
    )
    state.entity_states, accepted, errors = apply(
        state.entity_states,
        [
            {
                "operation": "record",
                "target_id": "HIDDEN_RING",
                "kind": "item_state",
                "part": "damage",
                "detail": DETAIL,
                "evidence": DETAIL,
                "visibility": "private",
            }
        ],
        targets={"HIDDEN_RING"},
        item_targets={"HIDDEN_RING"},
        narration=DETAIL,
        message_id="state-source",
        session_id="session-1",
        minute=1,
    )
    assert accepted and not errors
    db.add(ChatMessage(id="state-source", session_id="session-1", role="assistant", content=DETAIL))
    await db.commit()
    return user, state


@pytest.mark.parametrize(
    "workflow,protocol,notebook",
    [
        ("staged", "json", False),
        ("staged", "native", True),
        ("staged", "json", True),
        ("integrated", "native", False),
        ("integrated", "json", False),
        ("integrated", "native", True),
        ("integrated", "json", True),
    ],
)
async def test_current_state_reaches_decision_narrator_and_existing_extractor(
    monkeypatch, workflow, protocol, notebook
):
    roles = StateRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, workflow, protocol, notebook)
        before = read(state.entity_states).model_dump(exclude={"last_check"})
        manager, chunks = await run(db, user, ACTION)
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        saved = load(manager.state)
        evidence = saved.actors["LINA"].agent_evidence
        assert any(DETAIL in row.text and row.current_turn for row in evidence)
        assert DETAIL in json.dumps(roles.proposal_inputs[-1])
        assert "current_observable_state" in json.dumps(roles.prompts, default=str)
        assert DETAIL in json.dumps(roles.prompts, default=str)
        assert roles.reconciliations
        supplied = roles.reconciliations[-1]
        assert supplied["owners"]["HIDDEN_RING"] == "LINA"
        assert supplied["physical_conditions"]["active"][0]["detail"] == DETAIL
        ledger = read(manager.state.entity_states)
        assert ledger.model_dump(exclude={"last_check"}) == before
        assert ledger.last_check["status"] == "complete"
        assert ledger.last_check["accepted"] == ledger.last_check["rejected"] == []
        assert "inspect_entity" in str(saved.actors["LINA"].agent_audit)
        assert saved.usage.calls == (4 if workflow == "integrated" else 5)


async def test_rejected_turn_does_not_publish_state_observation_or_change_existing_facts(
    monkeypatch,
):
    roles = StateRoles(reject=True)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "staged", "json", False)
        before, before_facts = load(state), read(state.entity_states)
        _, chunks = await run(db, user, ACTION)
        assert any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        await db.refresh(state)
        assert load(state) == before
        assert read(state.entity_states) == before_facts
