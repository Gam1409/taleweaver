"""Bounded tool calls participate in real VN commit and rollback; no paid model calls."""

import json
from types import SimpleNamespace

import pytest

from backend.engine.chpm import agent, capacity, inference, rendering
from backend.engine.chpm.schema import KernelState, Settings, Usage
from backend.engine.chpm.state import KEY, load
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_state import mind
from tests.test_chpm_host_turn import configured, run
from tests.test_chpm_kernel import observation
from tests.test_chpm_reliability import Replies
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import install_roles


class AgentRoles(ChpmRoles):
    def __init__(self, fault=None):
        super().__init__(reject=fault == "review")
        self.fault = fault

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") != "agent_lookup":
            return await super().simple(system, payload, model, **kwargs)
        self.chpm_calls.append("agent_lookup")
        if self.fault == "json":
            return '{"broken":'
        if self.fault == "timeout":
            raise TimeoutError("offline simulated timeout")
        body = json.loads(payload)
        requests = [] if body["previous_lookups"] else [{"tool": "inspect_self"}]
        return json.dumps(
            {"purpose": "Check my possessions before responding.", "requests": requests}
        )


@pytest.mark.parametrize("fault", [None, "json", "timeout", "review"])
async def test_agent_turn_commits_only_after_review_and_failures_keep_original_state(
    monkeypatch, fault
):
    roles = AgentRoles(fault)
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, state = await configured(db)
        current = load(state)
        current.settings = Settings(
            mode="live",
            actor_ids=["LINA"],
            agent_steps=2,
            max_calls_per_turn=8,
            failure_policy="strict",
        )
        state.entity_states = {**state.entity_states, KEY: current.model_dump()}
        await db.commit()
        before = load(state)
        manager, chunks = await run(db, user)
        if fault in {"timeout", "review"}:
            assert any(c.startswith("event: error") for c in chunks), "".join(chunks)
            assert not any(c.startswith("event: chunk") for c in chunks)
            await db.refresh(state)
            assert load(state) == before
            return
        assert any(c.startswith("event: final") for c in chunks), "".join(chunks)
        saved = load(manager.state)
        audit = saved.actors["LINA"].agent_audit
        if fault == "json":
            assert len(audit) == 1 and audit[0]["stop"] == "invalid_plan"
            assert audit[0]["lookup_performed"] is False
            assert saved.usage.calls == 4
            assert roles.proposal_inputs[0]["agent_plan_status"] == ["invalid_plan"]
            assert roles.chpm_calls == ["perception", "agent_lookup", "proposal", "validation"]
            return
        assert len(audit) == 2 and audit[-1]["stop"] == "ready"
        assert saved.usage.calls == 5
        assert roles.chpm_calls == [
            "perception",
            "agent_lookup",
            "agent_lookup",
            "proposal",
            "validation",
        ]
        evidence = roles.proposal_inputs[0]["appraisal_context"]["visible_evidence"]
        assert any(e["source_id"].startswith("a") and "HIDDEN_RING" in e["text"] for e in evidence)
        assert saved.minds["LINA"].genesis.identity.description == "Values honesty."


async def test_stop_early_and_exhaust_rounds_without_spending_reserved_proposal_calls():
    response = json.dumps(
        {
            "purpose": "Look for the promise",
            "requests": [{"tool": "search_memory", "argument": "promise"}],
        }
    )
    model = Replies([response, response])
    host = SimpleNamespace(game_id="session", _chpm_model_factory=lambda role: model)
    usage = Usage()
    settings = Settings(mode="live", actor_ids=["npc"], agent_steps=2)
    tools, audit = await agent.investigate(host, settings, usage, mind(), observation(), {})
    assert usage.calls == 2 and audit[-1]["stop"] == "step_limit"
    assert not tools.pins and tools.mind == mind()
    model = Replies([json.dumps({"purpose": "Enough information", "requests": []})])
    host._chpm_model_factory = lambda role: model
    usage = Usage()
    _, audit = await agent.investigate(host, settings, usage, mind(), observation(), {})
    assert usage.calls == 1 and audit[0]["stop"] == "ready"


def test_admission_reserves_agent_rounds_for_each_active_npc_and_defaults_off():
    assert Settings().agent_steps == 0
    settings = Settings(mode="live", actor_ids=["a", "b", "c"], agent_steps=2)
    assert capacity.required_calls(settings) == 14
    with pytest.raises(ValueError, match="at least 14"):
        capacity.ensure_budget(KernelState(settings=settings), settings.actor_ids)
    settings.max_calls_per_turn = 14
    capacity.ensure_budget(KernelState(settings=settings), settings.actor_ids)
    settings.mode = "shadow"
    assert capacity.required_calls(settings) == 4


async def test_agent_rejects_session_mismatch_before_inference():
    host = SimpleNamespace(game_id="other-session")
    with pytest.raises(ValueError, match="another session"):
        await agent.investigate(host, Settings(agent_steps=1), Usage(), mind(), observation(), {})


def test_envelope_two_migrates_without_enabling_agent_or_changing_budget():
    raw = KernelState().model_dump()
    raw["schema_version"] = 2
    raw["settings"].pop("agent_steps")
    saved_budget = raw["settings"]["max_calls_per_turn"]
    restored = KernelState.model_validate(raw)
    assert restored.schema_version == 6 and restored.settings.agent_steps == 0
    assert restored.settings.max_calls_per_turn == saved_budget
    assert raw["schema_version"] == 2 and "agent_steps" not in raw["settings"]


async def test_matrix_agent_mode_records_calls_trace_and_original_identity_offline():
    from backend.engine.chpm.evaluation import matrix_cli, matrix_runner
    from tests.test_chpm_matrix import Models, case

    class LookupModel(Models):
        async def aexecute_simple_task(self, system, content, model, **kwargs):
            if kwargs["phase"] == "agent_lookup":
                return json.dumps(
                    {
                        "purpose": "Recall an observed promise",
                        "requests": [{"tool": "search_memory", "argument": "promise"}],
                    }
                )
            return await super().aexecute_simple_task(system, content, model, **kwargs)

    plan = matrix_cli.manifest([case(1, 12)], agent_steps=2, max_input_chars=32000)
    assert plan["max_logical_calls"] == 9 and plan["agent_steps"] == 2
    result = await matrix_runner.run(
        case(1, 12), LookupModel(), agent_steps=2, max_input_chars=32000
    )
    assert result["status"] == "ok", result["error"]
    assert result["identity_unchanged"]
    assert len([c for c in result["calls"] if c["phase"] == "agent_lookup"]) == 2
    assert result["decisions"]["npc-01"]["agent_audit"][-1]["stop"] == "step_limit"
    with pytest.raises(ValueError, match="25-call"):
        matrix_cli.manifest([case(20)], all_present=True, agent_steps=2)


async def test_cosmetic_purpose_length_does_not_reject_valid_tool_requests():
    purpose = "A long explanation about why I need this source. " * 8
    model = Replies(
        [
            json.dumps(
                {"purpose": purpose, "requests": [{"tool": "search_memory", "argument": "promise"}]}
            )
        ]
    )
    host = SimpleNamespace(game_id="session", _chpm_model_factory=lambda role: model)
    usage = Usage()
    _, audit = await agent.investigate(
        host, Settings(agent_steps=1), usage, mind(), observation(), {}
    )
    assert usage.calls == 1 and audit[0]["results"][0]["status"] == "ok"
    assert audit[0]["purpose"] == purpose[:180] and audit[0]["purpose_truncated"]
    assert audit[0]["stop"] == "step_limit"


@pytest.mark.parametrize(
    "requests",
    [
        [{"tool": "invented_tool", "argument": "secret"}],
        [{"tool": "search_memory", "argument": "x" * 161}],
        [{"tool": "inspect_self"}] * 3,
    ],
)
async def test_invalid_optional_plan_executes_nothing_and_records_visible_degradation(requests):
    model = Replies([json.dumps({"requests": requests})])
    host = SimpleNamespace(game_id="session", _chpm_model_factory=lambda role: model)
    usage = Usage()
    before = mind()
    tools, audit = await agent.investigate(
        host,
        Settings(agent_steps=2),
        usage,
        before,
        observation(),
        {},
    )
    assert usage.calls == 1
    assert tools.mind == before and not tools.pins
    assert audit == [
        {
            "purpose": "",
            "requests": [],
            "results": [],
            "stop": "invalid_plan",
            "error_type": "InvalidResponseError",
            "lookup_performed": False,
        }
    ]


async def test_optional_plan_transport_failure_still_stops_the_turn():
    from unittest.mock import AsyncMock

    model = Replies([])
    model.aexecute_simple_task = AsyncMock(side_effect=TimeoutError())
    host = SimpleNamespace(game_id="session", _chpm_model_factory=lambda role: model)
    with pytest.raises(ValueError, match="TimeoutError"):
        await agent.investigate(host, Settings(agent_steps=2), Usage(), mind(), observation(), {})
    model.aexecute_simple_task.assert_awaited_once()
