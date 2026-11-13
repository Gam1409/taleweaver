"""Legacy rejection hooks preserve results and emit only opt-in rejected proposals."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.system_diagnostics import service
from backend.engine.clothing.planning import WardrobePlan
from backend.engine.clothing.runtime import apply_wardrobe
from backend.engine.gameplay.guardrails import TurnGuardrailEnforcer
from backend.engine.mutation_targets import validate_mutation_targets
from backend.engine.rule_engine import GameEvent, WorldEntityUpdate
from backend.engine.scripting.context import GameContext
from backend.engine.visual_novel.event_policy import enforce_vn_event_policy
from backend.models.world_entity import WorldEntity
from tests.state_trace_support import (
    event_payloads,
    isolate_trace_directory,
    trace_files,
    trace_rows,
)
from tests.test_clothing_runtime import action, creation, world


@pytest.fixture(autouse=True)
def isolated_trace(tmp_path, monkeypatch):
    yield from isolate_trace_directory(tmp_path, monkeypatch)


def _manager():
    manager, _, _ = world()
    manager.game_id = manager.state.session_id
    manager.state.template_id = None
    manager.state.quests = [{"id": "Q", "required_item_id": "KEY"}]
    manager.state.completed_guard_expression = "False"
    manager.state.gameover_guard_expression = "False"
    manager.avatar.hp = 100
    manager.adventure = SimpleNamespace(
        awards=[{"key": "A", "requirement": "Find the remote relic."}]
    )
    entities = [
        WorldEntity(
            id="RELIC",
            name="Remote relic",
            entity_type="OBJECT",
            description="A relic.",
            current_scene_id="OTHER",
            inventory=[],
        )
    ]
    manager.db.execute = AsyncMock(
        return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: entities))
    )
    return manager


async def _mutation(rejected):
    manager = _manager()
    event = GameEvent(
        updated_entities=[
            {"entity_id": "MISSING" if rejected else "RELIC", "description": "Moved"}
        ],
        new_world_memories=[{"description": "The proposed change happened."}] if rejected else None,
        remember_notes=["Remember the proposed change."] if rejected else None,
    )
    result = await validate_mutation_targets(manager, event)
    return {"result": result, "event": event.model_dump()}


async def _vn(rejected):
    event = GameEvent(
        hp_change=-3 if rejected else 0,
        completed_quest_ids=["Q"] if rejected else [],
        game_over=rejected,
        updated_entities=[
            WorldEntityUpdate(entity_id="ANNA", hp=0 if rejected else None, notes="Still waiting")
        ],
    )
    enforce_vn_event_policy(event, {"rule_enforcement_mode": "vn"})
    return event.model_dump()


async def _progress(rejected):
    enforcer = TurnGuardrailEnforcer(_manager())
    event = GameEvent(
        completed_quest_ids=["Q"] if rejected else ["UNKNOWN_ALLOWED"],
        earned_award_keys=["A"] if rejected else [],
        game_over=rejected,
        game_completed=rejected,
        status_note="A proposed ending" if rejected else None,
    )
    await enforcer._enforce_quest_and_award_guardrails(event)
    result = await enforcer._enforce_win_and_loss_guardrails(event)
    return {"result": result, "event": event.model_dump()}


async def _script(rejected):
    context = GameContext(current_scene_id="ROOM")
    context.vars.set("unchanged_rule", True)
    if rejected:
        context.story.reject_action("The gate remains closed until the key is held.")
    else:
        context.story.narrate("The character waits.")
    return deepcopy(vars(context.changeset))


async def _clothing(rejected, failure="action"):
    manager, _, _ = world()
    event = GameEvent()
    plan = WardrobePlan(message_id="M1", scene_id="ROOM")
    if failure == "plan" and rejected:
        plan.errors = ["A wardrobe change lacked completed action evidence or character agency."]
    elif failure == "creation":
        plan.creations = [creation(acquisition="gift", source_id="ABSENT")] if rejected else []
    else:
        plan.actions = [action(item_id="MISSING" if rejected else "coat")]
    if failure == "presence" and rejected:
        plan.scene_id = "OTHER"
    event._vn_clothing_plan = plan
    result = await apply_wardrobe(manager, event, manager.state.entity_states)
    return {
        "result": result,
        "event": event.model_dump(),
        "inventory": deepcopy(manager.avatar.inventory),
        "visual_profile": deepcopy(manager.avatar.visual_profile),
        "state": deepcopy(manager.state.entity_states),
    }


async def _run(scenario, rejected):
    if scenario.startswith("clothing_"):
        return await _clothing(rejected, scenario.removeprefix("clothing_"))
    return await {
        "mutation_targets": _mutation,
        "visual_novel": _vn,
        "progression": _progress,
        "scripting": _script,
    }[scenario](rejected)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        "mutation_targets",
        "visual_novel",
        "progression",
        "scripting",
        "clothing_plan",
        "clothing_action",
        "clothing_presence",
        "clothing_creation",
    ],
)
async def test_legacy_rejection_trace_is_opt_in_and_does_not_change_results(scenario):
    from backend.core.state_rejection_trace import scope

    service.set_enabled(True, state_failure_traces=False)
    with scope(session_id="S", turn_id="T", operation=scenario):
        disabled = await _run(scenario, True)
    assert trace_files() == []
    service.set_enabled(True, state_failure_traces=True)
    with scope(session_id="S", turn_id="T", operation=scenario):
        enabled = await _run(scenario, True)
    assert enabled == disabled
    assert len(trace_files()) == 1
    records = event_payloads(trace_rows(), "state.rejected")
    assert records
    expected_domain = "clothing" if scenario.startswith("clothing_") else scenario
    assert {record["domain"] for record in records} == {expected_domain}
    assert all(record["reason_code"] and record["reason"] for record in records)
    assert all("proposal" in record["details"] for record in records)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", ["mutation_targets", "visual_novel", "progression", "scripting", "clothing_action"]
)
async def test_accepted_legacy_updates_and_default_empty_fields_write_no_failure_file(scenario):
    from backend.core.state_rejection_trace import scope

    service.set_enabled(True, state_failure_traces=True)
    with scope(session_id="S", operation=scenario):
        await _run(scenario, False)
    assert trace_files() == []


@pytest.mark.asyncio
async def test_mutation_and_progress_traces_include_target_and_causal_current_facts():
    from backend.core.state_rejection_trace import scope

    service.set_enabled(True, state_failure_traces=True)
    with scope(session_id="S", operation="legacy_rejections"):
        await _mutation(True)
        await _progress(True)
    records = event_payloads(trace_rows(), "state.rejected")
    by_code = {record["reason_code"]: record for record in records}
    target = by_code["unknown_target"]["details"]
    assert target["target_id"] == "MISSING"
    assert target["proposal"]["description"] == "Moved"
    assert "RELIC" in target["allowed_target_ids"]
    rule = by_code["unmet_hard_rule"]
    assert "KEY" in rule["reason"]
    assert rule["details"]["target_id"] == "Q"
    assert rule["details"]["current_scene_id"] == "ROOM"
    unreachable = by_code["inaccessible_dependency"]["details"]
    assert unreachable["target_id"] == "A"
    assert "RELIC" not in unreachable["accessible_entity_ids"]
    assert unreachable["entities"][0]["current_scene_id"] == "OTHER"


def test_vn_explicit_zero_entity_health_is_a_proposal_but_empty_defaults_are_not():
    from backend.core.state_rejection_trace import scope

    service.set_enabled(True, state_failure_traces=True)
    event = GameEvent(updated_entities=[{"entity_id": "ANNA", "hp": 0, "notes": "Waiting"}])
    with scope(session_id="S", operation="vn_entity_health"):
        enforce_vn_event_policy(event, {"rule_enforcement_mode": "vn"})
    records = event_payloads(trace_rows(), "state.rejected")
    proposal = records[0]["details"]["proposal"]
    assert proposal["entity_updates"][0]["proposal"]["hp"] == 0
    assert proposal["entity_updates"][0]["target_id"] == "ANNA"
    assert proposal["event_fields"] == {}
    assert event.updated_entities[0].hp is None
    assert event.updated_entities[0].notes == "Waiting"


@pytest.mark.asyncio
async def test_script_and_clothing_rejections_retain_the_full_cause_and_proposal():
    from backend.core.state_rejection_trace import scope

    service.set_enabled(True, state_failure_traces=True)
    with scope(session_id="S", operation="script_and_clothing"):
        await _script(True)
        await _clothing(True)
        await _clothing(True, "creation")
    records = event_payloads(trace_rows(), "state.rejected")
    by_code = {record["reason_code"]: record for record in records}
    scripted = by_code["scripted_rejection"]
    assert scripted["reason"] == "The gate remains closed until the key is held."
    assert scripted["details"]["pending_changes"]["var_updates"] == {"unchanged_rule": True}
    clothing = by_code["clothing_action_rejected"]
    assert clothing["reason"] == "The character does not own that garment."
    assert clothing["details"]["proposal"]["item_id"] == "MISSING"
    assert clothing["details"]["proposal"]["evidence"] == "I put on my blue coat."
    assert clothing["details"]["actor"]["resolved_inventory"][0]["id"] == "coat"
    creation_record = by_code["clothing_creation_rejected"]
    assert creation_record["reason"] == "The giver is no longer present."
    assert creation_record["details"]["proposal"]["name"] == "Red scarf"
    assert creation_record["details"]["source_id"] == "ABSENT"


@pytest.mark.parametrize("mode", ["chat", "rpg"])
def test_legacy_modes_do_not_mark_accepted_mechanics_as_vn_rejections(mode):
    from backend.core.state_rejection_trace import scope

    event = GameEvent(hp_change=-3, game_over=True, completed_quest_ids=["Q"])
    before = event.model_dump()
    service.set_enabled(True, state_failure_traces=True)
    with scope(session_id="S", operation="legacy_mode"):
        enforce_vn_event_policy(event, {"rule_enforcement_mode": mode})
    assert event.model_dump() == before
    assert trace_files() == []


@pytest.mark.asyncio
async def test_processed_clothing_plan_does_not_emit_another_rejection_packet():
    from backend.core.state_rejection_trace import scope

    service.set_enabled(True, state_failure_traces=True)
    manager, _, _ = world()
    event = GameEvent()
    event._vn_clothing_plan = WardrobePlan(
        message_id="M1", scene_id="ROOM", actions=[action(item_id="MISSING")]
    )
    with scope(session_id="S", operation="initial_attempt"):
        await apply_wardrobe(manager, event, manager.state.entity_states)
    assert len(trace_files()) == 1
    with scope(session_id="S", operation="already_processed"):
        await apply_wardrobe(manager, event, manager.state.entity_states)
    assert len(trace_files()) == 1
