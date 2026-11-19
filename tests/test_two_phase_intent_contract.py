"""Physical intent has an explicit, portable schema and a reserved execution round."""

from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from backend.engine.chpm import parallel_budget
from backend.engine.chpm.performance import actor_id
from backend.engine.chpm.two_phase_decision import PhysicalIntent


def test_explicit_phase_a_schema_survives_transport_and_rejects_non_world_steps():
    adapter = TypeAdapter(PhysicalIntent)
    validator = Draft202012Validator(adapter.json_schema())
    valid = [
        {"mode": "none", "steps": []},
        {"mode": "act", "steps": [{"tool": "take_item", "item_id": "cup"}]},
        {"mode": "act", "steps": [{"tool": "set_pose", "posture": "sitting"}]},
    ]
    for candidate in valid:
        assert validator.is_valid(candidate)
        assert adapter.validate_python(candidate).model_dump() == candidate
    invalid = [
        {"mode": "none"},
        {"mode": "act", "steps": []},
        {"mode": "none", "steps": valid[1]["steps"]},
        {"mode": "act", "steps": valid[1]["steps"] * 3},
        {"mode": "act", "steps": [{"tool": "inspect_entity", "argument": "cup"}]},
        {"mode": "act", "steps": [{"tool": "discard_actions"}]},
        {"mode": "act", "steps": [{"tool": "take_item", "item_id": "cup", "actor_id": "@player"}]},
    ]
    for candidate in invalid:
        assert not validator.is_valid(candidate)
        with pytest.raises(ValidationError):
            adapter.validate_python(candidate)


def test_reserved_physical_execution_survives_phase_a_proposal_repair():
    token = actor_id.set("A")
    try:
        with parallel_budget.reserve(["A", "B"], 4):
            parallel_budget.dispatched("integrated_decision")
            parallel_budget.dispatched("physical_intent_accepted")
            parallel_budget.dispatched("proposal_repair")
            assert parallel_budget.remaining(0) == 5
            parallel_budget.dispatched("npc_execution")
            assert parallel_budget.remaining(0) == 4
    finally:
        actor_id.reset(token)


def test_postcondition_failure_does_not_reexport_private_actor_diagnostics(monkeypatch):
    from backend.engine.chpm import runtime
    from backend.engine.npc_actions.postconditions import PostconditionViolationError

    # The publication owner already records the operation and field. Its caller must
    # propagate the transaction failure without attaching every observer's private mind.
    monkeypatch.setattr(runtime, "reject", lambda *a, **kw: pytest.fail("duplicate full trace"))
    with pytest.raises(PostconditionViolationError):
        runtime._preparation_failed(
            SimpleNamespace(game_id="session"),
            SimpleNamespace(),
            PostconditionViolationError("mismatch"),
        )
