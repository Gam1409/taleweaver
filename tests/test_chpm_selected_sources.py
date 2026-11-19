"""Selected own prose is the source, never an independently repeated typed command."""

import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.engine import turn_controls
from backend.engine.chpm import inference, physical_resolution, tool_operations, two_phase_selection
from backend.engine.chpm.errors import StaleControlError
from backend.engine.chpm.schema import Settings, Usage
from backend.engine.chpm.two_phase_decision import Act
from backend.engine.npc_actions import selected_sources
from backend.engine.npc_actions.acknowledgment_contracts import PublicationAcknowledgment
from backend.engine.npc_actions.contracts import TakeOff
from tests.observable_state_support import tools_for, world
from tests.test_chpm_native_notebook_loop import call, turn
from tests.test_npc_action_previews import fixture


def test_phase_a_accepts_own_words_without_a_tool_or_operands():
    selected = Act.model_validate({"mode": "act", "steps": ["I pick up the copper cup."]})
    assert selected.steps == ["I pick up the copper cup."]


def test_phase_a_optional_observer_references_do_not_require_a_tool():
    phrase = {"text": "I remove my coat and hand it to Sam.", "target_refs": ["COAT", "SAM"]}
    selected = Act.model_validate({"mode": "act", "steps": [phrase]})
    assert selected.steps[0].text == phrase["text"]
    assert selected.steps[0].target_refs == ("COAT", "SAM")


def test_phase_a_rejects_a_typed_command_in_place_of_selected_words():
    with pytest.raises(ValidationError):
        Act.model_validate({"mode": "act", "steps": [{"tool": "take_item", "item_id": "CUP"}]})


def selection_case(monkeypatch, groups, *, choices=None, after=None, prior_repairs=1):
    manager, _, draft = fixture()
    tools = tools_for(*world())
    tools.actions = draft
    captured = tool_operations.capture(manager, tools)
    settings = Settings(mode="live", actor_ids=["npc"], max_calls_per_turn=8)
    usage, queries = Usage(proposal_repairs=prior_repairs), []

    async def request(_manager, _settings, _usage, messages, offered, **kwargs):
        queries.append((deepcopy(messages), deepcopy(offered)))
        usage.calls += 1
        if after:
            after(manager)
        actual = groups(len(queries)) if callable(groups) else groups
        return turn(
            call(
                f"resolution-call-{len(queries)}", "resolve_selected_steps", {"resolutions": actual}
            )
        )

    monkeypatch.setattr(inference, "tool_request", request)

    async def execute():
        words = Act.model_validate(
            {
                "mode": "act",
                "steps": choices or [{"text": "I pick up the key.", "target_refs": ["KEY"]}],
            }
        ).steps
        return (
            await two_phase_selection.execute(
                manager,
                settings,
                usage,
                tools,
                SimpleNamespace(protocol="native"),
                captured,
                set(),
                words,
            )
        )[0]

    return execute, draft, queries, manager


def action(passage="p0", **changes):
    return {
        "passage_id": passage,
        "disposition": "action",
        "actions": [{"tool": "take_item", "item_id": "KEY", **changes}],
    }


@pytest.mark.parametrize("groups", [[], [action("p1")], [action(), action()]])
async def test_resolution_cannot_skip_borrow_or_duplicate_a_selected_phrase(monkeypatch, groups):
    execute, draft, _, _ = selection_case(monkeypatch, groups)
    report = await execute()
    assert report["status"] == "rejected" and draft.requests == []
    assert report["error_type"] in {"source_coverage_mismatch", "invalid_arguments"}


async def test_visible_wrong_substitution_cannot_replace_actor_selected_reference(monkeypatch):
    execute, draft, _, _ = selection_case(monkeypatch, [action(item_id="CHEST")])
    assert {"KEY", "CHEST"} <= draft.scope.accessible_ids
    report = await execute()
    assert report["error_type"] == "selected_target_mismatch" and not draft.requests
    assert report["failure_stage"] == "interpretation"


async def test_two_eligible_items_without_selected_references_are_not_a_free_choice(monkeypatch):
    execute, draft, _, _ = selection_case(monkeypatch, [action()], choices=["I take an item."])
    report = await execute()
    assert report["error_type"] == "ambiguous_target" and not draft.requests


async def test_prose_without_references_executes_when_the_eligible_item_is_unique(monkeypatch):
    execute, draft, _, _ = selection_case(monkeypatch, [action()], choices=["I take the key."])
    draft.scope = replace(draft.scope, accessible_ids=frozenset({"npc", "KEY"}))
    report = await execute()
    assert report["status"] == "staged" and draft.requests[0].item_id == "KEY"


def test_wear_eligibility_uses_garments_and_current_wear_not_ordinary_tokens():
    _, _, draft = fixture()
    assert draft.selected_item_candidates("take_off_item") == {"COAT", "LINING"}
    draft.execute(TakeOff(tool="take_off_item", item_id="COAT"))
    assert draft.selected_item_candidates("wear_item") == {"COAT"}
    assert "FLASK" not in draft.selected_item_candidates("wear_item")


async def test_unknown_selected_reference_is_not_promoted_by_a_non_effect(monkeypatch):
    execute, draft, queries, _ = selection_case(
        monkeypatch,
        [{"passage_id": "p0", "disposition": "no_effect", "reason": "offer"}],
        choices=[{"text": "I offer an unseen item.", "target_refs": ["HIDDEN"]}],
    )
    report = await execute()
    assert report["status"] == "rejected" and report["error_type"] == "unavailable_target"
    assert not queries and not draft.requests
    projected = selected_sources.for_context(draft.selected_execution.source_selection)
    assert "HIDDEN" not in json.dumps(projected)


@pytest.mark.parametrize("reference", ["HIDDEN", "AWAY", "other"])
async def test_hidden_foreign_role_and_away_operands_never_stage(monkeypatch, reference):
    execute, draft, _, _ = selection_case(monkeypatch, [action(item_id=reference)])
    report = await execute()
    assert report["error_type"] == "unavailable_target" and not draft.requests


async def test_unavailable_effect_is_interpretation_failure_before_world_preview(monkeypatch):
    group = {
        "passage_id": "p0",
        "disposition": "action",
        "actions": [{"tool": "set_pose", "posture": "sitting"}],
    }
    execute, draft, queries, _ = selection_case(monkeypatch, [group])
    assert "set_pose" not in draft.available_tools()
    report = await execute()
    assert report["error_type"] == "unavailable_actions"
    assert report["failure_stage"] == "interpretation" and len(queries) == 1
    assert not draft.requests


async def test_compound_source_has_distinct_ordered_operations_and_live_second_preview(monkeypatch):
    group = action()
    group["actions"].append({"tool": "put_down_item", "item_id": "KEY"})
    execute, draft, queries, _ = selection_case(monkeypatch, [group])
    report = await execute()
    assert report["status"] == "staged" and len(queries) == 1
    assert [request.tool for request in draft.requests] == ["take_item", "put_down_item"]
    assert draft.working_copy()[1].owners["KEY"] == draft.scope.possessions.owners["KEY"]
    trace = draft.selected_execution.source_selection
    assert trace.selection.passages[0].model_dump(include={"text", "start", "end"}) == {
        "text": "I pick up the key.",
        "start": 0,
        "end": len("I pick up the key."),
    }
    links = trace.resolutions[0].actions
    assert [link.ordinal for link in links] == [0, 1]
    assert [link.operation_id for link in links] == [op.operation_id for op in draft.operations]
    assert links[0].operation_id != links[1].operation_id
    assert links[1].depends_on == links[0].operation_id
    assert all(op.tool_call_id == "resolution-call-1" for op in draft.operations)
    assert trace.selection.control.operation_id not in {link.operation_id for link in links}


async def test_provider_group_order_does_not_replace_host_source_order(monkeypatch):
    groups = [
        {
            "passage_id": "p1",
            "disposition": "action",
            "actions": [{"tool": "give_item", "item_id": "KEY", "recipient_id": "other"}],
        },
        action(),
    ]
    choices = [
        {"text": "I pick up the key.", "target_refs": ["KEY"]},
        {"text": "I hand it to the other person.", "target_refs": ["KEY", "other"]},
    ]
    execute, draft, _, _ = selection_case(monkeypatch, groups, choices=choices)
    report = await execute()
    assert report["status"] == "staged"
    assert [request.tool for request in draft.requests] == ["take_item", "give_item"]
    assert [row.passage_id for row in draft.selected_execution.source_selection.resolutions] == [
        "p0",
        "p1",
    ]


@pytest.mark.parametrize("reason", ["offer", "past", "negated", "future", "incidental"])
async def test_explicit_semantic_non_effect_keeps_private_source_without_a_receipt(
    monkeypatch, reason
):
    execute, draft, _, _ = selection_case(
        monkeypatch, [{"passage_id": "p0", "disposition": "no_effect", "reason": reason}]
    )
    report = await execute()
    assert report["status"] == "no_effect" and not draft.requests and not draft.operations
    assert draft.selected_execution.source_selection.resolutions[0].reason == reason


async def test_unrepresented_stable_effect_rejects_entire_selection(monkeypatch):
    groups = [
        action(),
        {"passage_id": "p1", "disposition": "unresolved", "reason": "unsupported_effect"},
    ]
    execute, draft, _, _ = selection_case(
        monkeypatch,
        groups,
        choices=[{"text": "I take the key.", "target_refs": ["KEY"]}, "I create a new staircase."],
    )
    report = await execute()
    assert report["error_type"] == "unsupported_effect" and not draft.requests


async def test_malformed_correction_cannot_reuse_prior_rejected_operations(monkeypatch):
    execute, draft, queries, _ = selection_case(
        monkeypatch,
        lambda count: [action(item_id="CHEST")] if count == 1 else [],
        prior_repairs=0,
    )
    report = await execute()
    trace = draft.selected_execution.source_selection
    assert report["status"] == "rejected" and len(queries) == 2
    assert [error["code"] for error in report["gate_errors"]] == [
        "selected_target_mismatch",
        "invalid_arguments",
    ]
    assert trace.resolutions == () and trace.resolution_call_id is None
    assert draft.selected_execution.steps == () and draft.operations == []


async def test_non_effect_correction_retains_diagnostics_without_inventing_failure(monkeypatch):
    execute, draft, _, _ = selection_case(
        monkeypatch,
        lambda count: (
            []
            if count == 1
            else [{"passage_id": "p0", "disposition": "no_effect", "reason": "offer"}]
        ),
        prior_repairs=0,
    )
    report = await execute()
    assert report["status"] == "no_effect" and report["repaired"]
    assert (
        draft.requests == [] and draft.selected_execution.gate_errors[0].code == "invalid_arguments"
    )


async def test_two_current_unresolved_phrases_do_not_overflow_prior_failure_history(monkeypatch):
    groups = [
        {"passage_id": "p0", "disposition": "unresolved", "reason": "unsupported_effect"},
        {"passage_id": "p1", "disposition": "unresolved", "reason": "ambiguous"},
    ]
    execute, draft, _, _ = selection_case(
        monkeypatch,
        lambda count: [] if count == 1 else groups,
        prior_repairs=0,
        choices=["I create a new staircase.", "I move that thing."],
    )
    report = await execute()
    assert len(report["gate_errors"]) == 3
    assert [row.code for row in draft.selected_execution.gate_errors] == [
        "unsupported_effect",
        "ambiguous",
    ]
    assert len(draft.selected_execution.source_selection.resolutions) == 2


async def test_late_resolution_cannot_borrow_new_attempt_or_cosmetic_state_fence(monkeypatch):
    execute, draft, _, _ = selection_case(monkeypatch, [action()], after=turn_controls.begin)
    with pytest.raises(StaleControlError):
        await execute()
    assert not draft.requests and not draft.approved


async def test_cosmetic_revision_is_audit_only_and_selected_snapshot_is_immutable(monkeypatch):
    def cosmetic(manager):
        manager.state.entity_states = {"portrait": {"emotion": "neutral"}}

    execute, draft, _, _ = selection_case(monkeypatch, [action()], after=cosmetic)
    report = await execute()
    assert report["status"] == "staged" and draft.requests


def test_resolution_schema_hides_disabled_operations_and_unreachable_definitions():
    offered = physical_resolution.definition({"take_item"})[0]["function"]["parameters"]
    wire = json.dumps(offered)
    assert "take_item" in wire and "give_item" not in wire and "Posture" not in wire
    assert "discriminator" not in wire


@pytest.mark.parametrize(
    "changes",
    [
        {"disposition": "no_effect"},
        {"reason": "past"},
        {"actions": []},
        {
            "actions": [
                {"ordinal": 0, "operation_id": "a", "tool": "take_item", "depends_on": "foreign"}
            ]
        },
    ],
)
def test_persisted_resolution_cannot_certify_non_effect_or_foreign_dependencies(changes):
    host, scope, _ = fixture()
    selected = selected_sources.capture(scope.control, "npc", ["I take the key."])
    row = {
        "passage_id": "p0",
        "disposition": "action",
        "actions": [{"ordinal": 0, "operation_id": "a", "tool": "take_item"}],
    }
    with pytest.raises(ValidationError):
        selected_sources.SelectionTrace.model_validate(
            {"selection": selected.model_dump(), "resolutions": [{**row, **changes}]}
        )
    assert host.game_id


def test_legacy_execution_and_acknowledgment_preserve_saved_shape():
    raw = {
        "attempt_id": "prior",
        "operations": [],
        "execution": {"status": "not_attempted", "steps": [], "gate_errors": []},
    }
    assert PublicationAcknowledgment.model_validate(raw).model_dump(mode="json") == raw
