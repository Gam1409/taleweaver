"""Current rejected commands reach prose consumers without becoming world effects."""

import json
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine import turn_controls
from backend.engine.chpm.state import KEY, load
from backend.engine.npc_actions import control, feedback
from backend.engine.npc_actions.contracts import ChangeState, Give, Take
from backend.models.avatar import Avatar
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_chpm_action_turn import ActionRoles
from tests.test_chpm_host_turn import run
from tests.test_chpm_notebook_turn import ACTION, install
from tests.test_chpm_observable_turn import prepare
from tests.test_vn_turn_integration import NARRATION


class RejectedKeyRoles(ActionRoles):
    def __init__(self):
        super().__init__()
        self.reviews = []

    @staticmethod
    def commands():
        return [
            {"name": "take_item", "arguments": {"item_id": "BRASS_KEY"}},
            {
                "name": "give_item",
                "arguments": {"item_id": "BRASS_KEY", "recipient_id": "@player"},
            },
        ]

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") == "validation":
            self.reviews.append((system, json.loads(payload)))
        return await super().simple(system, payload, model, **kwargs)


async def prepare_rejected_key(db, protocol):
    user, state = await prepare(db, "integrated", protocol, False)
    kernel = load(state)
    kernel.settings.action_tools = True
    state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
    avatar = await db.scalar(select(Avatar))
    avatar.inventory = [{"id": "BRASS_KEY", "name": "Brass key"}]
    db.add(
        WorldEntity(
            id="SPARE_ITEM",
            session_id=state.session_id,
            entity_type="OBJECT",
            name="Spare item",
            description="A loose ordinary item.",
            current_scene_id="START",
            is_hidden=False,
            is_in_inventory=False,
            is_portable=True,
        )
    )
    await db.commit()
    return user, state


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_rejected_take_and_give_reach_narration_and_review_with_an_empty_plan(
    monkeypatch, protocol
):
    roles = RejectedKeyRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare_rejected_key(db, protocol)
        manager, events = await run(db, user, ACTION)
        assert any(event.startswith("event: final") for event in events), "".join(events)
        saved = load(manager.state)
        assert [
            row["status"] for step in saved.actors["LINA"].agent_audit for row in step["results"]
        ] == ["unavailable_entity", "unavailable_entity"]
        assert [item["id"] for item in manager.avatar.inventory] == ["BRASS_KEY"]
        assert len(roles.reviews) == 1
        review_system, supplied = roles.reviews[0]
        assert not supplied["contract"]["LINA"].get("authoritative_command_outcomes")
        records = supplied["contract"]["LINA"]["rejected_command_previews"]
        assert [record["tool"] for record in records] == ["take_item", "give_item"]
        assert all("item_id" not in record for record in records)
        assert records[1]["recipient_id"] == "@player"
        assert all(
            row["item_id"] == "BRASS_KEY"
            for step in saved.actors["LINA"].agent_audit
            for row in step["requests"]
        )
        assert all(record["reason_code"] == "unavailable_entity" for record in records)
        assert all(record["phase"] == "npc_tools" for record in records)
        assert "rejected_command_previews" in str(roles.prompts)
        assert "Rejected previews did not change the world" in review_system
        assert load(manager.state).usage.calls == 4


class RepairedKeyRoles(RejectedKeyRoles):
    def __init__(self):
        super().__init__()
        self.repairs = []

    async def simple(self, system, payload, model, **kwargs):
        phase = kwargs.get("phase")
        if phase == "validation" and not self.reviews:
            self.chpm_calls.append(phase)
            supplied = json.loads(payload)
            self.reviews.append((system, supplied))
            return json.dumps(
                {
                    "review_scope": supplied["review_scope"],
                    "matches": False,
                    "rejections": [{"reason_code": "world", "actor_id": "LINA"}],
                }
            )
        if phase == "repair":
            self.chpm_calls.append(phase)
            self.repairs.append((system, json.loads(payload)))
            return NARRATION
        return await super().simple(system, payload, model, **kwargs)


class OwnerRejectedRoles(RejectedKeyRoles):
    @staticmethod
    def commands():
        return [
            {"name": "give_item", "arguments": {"item_id": "HIDDEN_RING", "recipient_id": "LINA"}},
            {
                "name": "give_item",
                "arguments": {"item_id": "SPARE_ITEM", "recipient_id": "@player"},
            },
        ]


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_real_owner_rejection_is_feedback_without_aborting_the_turn(monkeypatch, protocol):
    roles = OwnerRejectedRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _ = await prepare_rejected_key(db, protocol)
        manager, events = await run(db, user, ACTION)
        assert any(event.startswith("event: final") for event in events), "".join(events)
        _, supplied = roles.reviews[0]
        records = supplied["contract"]["LINA"]["rejected_command_previews"]
        assert len(records) == 2
        assert records[0]["status"] == "blocked"
        assert records[0]["reason_code"] == "recipient_unavailable"
        assert "item_id" not in records[0]
        assert records[0]["recipient_id"] == "LINA"
        assert records[1]["item_id"] == "SPARE_ITEM"
        assert records[1]["recipient_id"] == "@player"
        assert records[1]["reason_code"] == "custody_changed"
        assert "HIDDEN_RING" not in json.dumps(records)
        assert any(
            row.get("item_id") == "HIDDEN_RING"
            for step in load(manager.state).actors["LINA"].agent_audit
            for row in step["requests"]
        )
        assert not supplied["contract"]["LINA"].get("authoritative_command_outcomes")
        assert load(manager.state).usage.calls == 4


async def test_existing_prose_repair_receives_the_same_rejected_preview_scope(monkeypatch):
    roles = RepairedKeyRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare_rejected_key(db, "json")
        manager, events = await run(db, user, ACTION)
        assert any(event.startswith("event: final") for event in events), "".join(events)
        assert len(roles.repairs) == 1
        repair_system, supplied = roles.repairs[0]
        assert "Rejected previews did not change the world" in repair_system
        assert supplied["dialogue_contract"]["LINA"]["rejected_command_previews"]
        assert load(manager.state).usage.calls == 6


def audited_turn(requests=None):
    binding = turn_controls.Binding(
        attempt_id="attempt_one",
        phase="npc_preparation",
        input_id="input",
        input_revision="revision",
        input_hash="1" * 64,
        state_revision="2" * 64,
    ).model_dump()
    summaries, results = [], []
    for index, request in enumerate(requests or [Take(tool="take_item", item_id="KEY")]):
        operation = turn_controls.operation(
            {**binding, "phase": "npc_tools"},
            request.tool,
            actor_id="LINA",
            tool_call_id=f"call_{index}",
        )
        summaries.append(
            {
                **feedback.summarize(request),
                "attempt_id": operation.attempt_id,
                "operation_id": operation.operation_id,
                "tool_call_id": operation.tool_call_id,
            }
        )
        results.append(
            control.result(operation, "unavailable_entity", reason_code="unavailable_entity")
        )
    decision = SimpleNamespace(
        actor_id="LINA",
        observation=SimpleNamespace(
            message_id="input", revision_id="revision", content_hash="1" * 64
        ),
        agent_audit=[{"requests": summaries, "results": results, "stop": "continue"}],
    )
    return SimpleNamespace(
        input_id="input",
        control=binding,
        decisions={"LINA": decision},
        action_outcomes={},
        action_drafts={},
    )


def audit(turn):
    return turn.decisions["LINA"].agent_audit[0]


@pytest.mark.parametrize(
    "location,field,value",
    [
        ("requests", "attempt_id", "other_attempt"),
        ("requests", "operation_id", "other_operation"),
        ("requests", "tool_call_id", "other_call"),
        ("results", "input_id", "other_input"),
        ("results", "input_revision", "other_revision"),
        ("results", "input_hash", "3" * 64),
        ("results", "actor_id", "OTHER"),
        ("results", "phase", "npc_command_publication"),
        ("results", "tool", "give_item"),
    ],
)
def test_foreign_or_mismatched_audit_cannot_enter_narration(location, field, value):
    turn = audited_turn()
    audit(turn)[location][0][field] = value
    with pytest.raises(control.CommandRejectedError, match="does not belong"):
        feedback.project(turn)


def test_results_associate_by_call_id_and_never_expose_private_fields():
    turn = audited_turn(
        [
            Take(tool="take_item", item_id="KEY"),
            Give(tool="give_item", item_id="RING", recipient_id="@player"),
        ]
    )
    record = audit(turn)
    record["purpose"] = "PRIVATE_VALUE"
    record["requests"][0].update(path="PRIVATE_VALUE", detail="PRIVATE_VALUE")
    record["results"][0].update(message="PRIVATE_VALUE", diagnostic_detail="PRIVATE_VALUE")
    record["results"].reverse()
    projected = feedback.project(turn)["LINA"]
    assert [row["item_id"] for row in projected] == ["KEY", "RING"]
    assert projected[1]["recipient_id"] == "@player"
    assert "PRIVATE_VALUE" not in json.dumps(projected)


def test_duplicate_results_and_unknown_semantic_references_are_rejected():
    turn = audited_turn()
    audit(turn)["results"].append(deepcopy(audit(turn)["results"][0]))
    with pytest.raises(control.CommandRejectedError):
        feedback.project(turn)
    turn = audited_turn()
    del audit(turn)["requests"][0]["item_id"]
    with pytest.raises(control.CommandRejectedError):
        feedback.project(turn)


def test_legacy_unbound_audit_stays_readable_without_gaining_control_authority():
    turn = audited_turn()
    turn.decisions["LINA"].agent_audit = [
        {
            "requests": [{"tool": "take_item", "path_hash": "old"}],
            "results": [{"status": "blocked"}],
        }
    ]
    assert feedback.project(turn) == {}


def test_legacy_bound_hash_only_summary_remains_readable_without_current_authority():
    turn = audited_turn()
    request = audit(turn)["requests"][0]
    del request["item_id"]
    request["path_hash"] = sha256(b"").hexdigest()
    assert feedback.project(turn) == {}


def test_retained_cached_audit_is_not_reinterpreted_as_a_new_attempt():
    turn = audited_turn()
    decision = turn.decisions["LINA"]
    decision.context_hash = "unchanged_semantic_context"
    turn.initial = SimpleNamespace(actors={"LINA": deepcopy(decision)})
    turn.control["attempt_id"] = "new_attempt"
    assert feedback.project(turn) == {}


def test_retained_decision_identity_cannot_legitimize_changed_operation_ids():
    turn = audited_turn()
    decision = turn.decisions["LINA"]
    decision.context_hash = "unchanged_semantic_context"
    turn.initial = SimpleNamespace(actors={"LINA": deepcopy(decision)})
    audit(turn)["requests"][0]["operation_id"] = "forged_operation"
    with pytest.raises(control.CommandRejectedError):
        feedback.project(turn)


def test_loaded_legacy_decision_can_be_cached_without_rebinding_its_audit():
    from backend.engine.chpm.kernel import existing
    from backend.engine.chpm.schema import KernelState
    from tests.test_chpm_kernel import decision as fixture_decision

    original = audited_turn()
    summary = audit(original)["requests"][0]
    del summary["item_id"]
    summary["path_hash"] = sha256(b"").hexdigest()
    decision = fixture_decision(content_hash="1" * 64, revision_id="revision").model_copy(
        update={"actor_id": "LINA", "agent_audit": deepcopy(original.decisions["LINA"].agent_audit)}
    )
    loaded = KernelState.model_validate_json(
        KernelState(actors={"LINA": decision}).model_dump_json()
    )
    cached = existing(loaded.actors["LINA"], decision.observation, decision.context_hash)
    original.control["attempt_id"] = "new_attempt"
    original.initial = loaded
    original.decisions = {"LINA": cached}
    assert feedback.project(original) == {}
    assert cached.agent_audit == decision.agent_audit


def test_generic_owner_failure_keeps_its_code_without_publishing_diagnostics():
    turn = audited_turn()
    current = audit(turn)["results"][0]
    operation = turn_controls.Operation.model_validate(
        {key: current[key] for key in turn_controls.Operation.model_fields if key in current}
    )
    audit(turn)["results"][0] = control.owner_failure(operation, ValueError("PRIVATE_VALUE"))
    record = feedback.project(turn)["LINA"][0]
    assert record["status"] == "blocked" and record["reason_code"] == "owner_rejected"
    assert "PRIVATE_VALUE" not in json.dumps(record)


def test_unparsed_arguments_keep_typed_feedback_without_inventing_a_target():
    turn = audited_turn()
    request, result = audit(turn)["requests"][0], audit(turn)["results"][0]
    del request["item_id"]
    request.update(arguments_hash="4" * 64, name_hash="5" * 64)
    result.update(status="invalid_arguments", reason_code="invalid_arguments")
    projected = feedback.project(turn)["LINA"][0]
    assert projected["reason_code"] == "invalid_arguments"
    assert "item_id" not in projected and "arguments_hash" not in projected


def test_action_summary_retains_ids_without_private_details_or_arbitrary_notebook_fields():
    from backend.engine.chpm.notebook_tools import request_summary

    request = ChangeState(
        tool="change_item_state",
        item_id="KEY",
        dimension="surface",
        detail="PRIVATE_VALUE",
        visibility="private",
    )
    assert request_summary(request) == {
        "tool": "change_item_state",
        "item_id": "KEY",
        "dimension": "surface",
    }


def test_applied_pose_supersedes_only_posture_not_placement_or_another_item_denial():
    from backend.engine.npc_actions.contracts import Approach

    turn = audited_turn(
        [
            Approach(tool="approach", target_id="@player", mode="crawl"),
            Take(tool="take_item", item_id="KEY"),
        ]
    )
    operation = turn_controls.operation(
        {**turn.control, "phase": "npc_command_publication"},
        "set_pose",
        actor_id="LINA",
        tool_call_id="later_call",
    )
    turn.action_drafts = {"LINA": SimpleNamespace(operations=[operation])}
    turn.action_outcomes = {
        "LINA": [control.result(operation, "applied", effect={"posture": "standing"})]
    }
    records = feedback.project(turn)["LINA"]
    assert records[0]["superseded_fields"] == ["posture"]
    assert "placement" not in records[0]["superseded_fields"]
    assert "superseded_fields" not in records[1]
