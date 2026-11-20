"""Verified property receipts require real, source-bound canonical ledger writes."""

from copy import deepcopy

import pytest

from backend.engine.npc_actions import postconditions, publication
from backend.engine.npc_actions.contracts import ChangeState, Interact, Take, Use
from backend.engine.physical_conditions.ledger import read
from backend.engine.physical_conditions.schema import KEY
from backend.engine.visual_novel.continuity import SCENE
from tests.conftest import TestSessionLocal
from tests.test_npc_action_publication import fixture
from tests.test_npc_two_phase_postconditions import approve, owners


def request(tool):
    if tool == "change_item_state":
        return ChangeState(
            tool=tool,
            item_id="KEY",
            dimension="surface",
            detail="PRIVATE_PROPERTY_VALUE",
            visibility="private",
        )
    return Use(
        tool=tool, item_id="KEY", extent="partial", remaining_detail="PRIVATE_PROPERTY_VALUE"
    )


def corrupt_identity(ledger, identifier, condition, fault):
    if fault == "missing_condition":
        ledger["conditions"].pop(identifier)
    elif fault == "wrong_id":
        condition["id"] = "wrong_condition"
        ledger["conditions"] = {condition["id"]: condition}
    else:
        duplicate = deepcopy(condition)
        duplicate["id"] = "duplicate_condition"
        ledger["conditions"][duplicate["id"]] = duplicate


def corrupt(states, fault):
    if fault == "custody":
        states["LINA"]["inventory"] = []
        states["SECOND"] = {"inventory": [{"id": "KEY", "name": "A key"}]}
        return
    if fault == "missing_ledger":
        states.pop(KEY)
        return
    ledger = states[KEY]
    if fault in {"invalid_ledger", "missing_event"}:
        ledger["conditions" if fault == "invalid_ledger" else "events"] = []
        return
    identifier, condition = next(iter(ledger["conditions"].items()))
    if fault in {"missing_condition", "wrong_id", "duplicate_dimension"}:
        corrupt_identity(ledger, identifier, condition, fault)
        return
    current = condition["latest"]["command"]["operation"]
    replacements = {
        "item": (("target_id",), "HIDDEN_RING"),
        "dimension": (("part",), "another_dimension"),
        "value": (("detail",), "PRIVATE_CORRUPTED_VALUE"),
        "visual_detail": (("visual_detail",), "PRIVATE_UNREQUESTED_EXPOSURE"),
        "visibility": (
            ("visibility",),
            "public" if condition["visibility"] == "private" else "private",
        ),
        "source_kind": (("latest", "kind"), "unavailable"),
        "source_actor": (("latest", "command", "actor_id"), "SECOND"),
        "source_operation": (
            ("latest", "command", "operation"),
            "use_item" if current == "change_item_state" else "change_item_state",
        ),
        "source_command": (("latest", "command", "id"), "unrelated-command"),
        "source_input": (("latest", "message_id"), "unrelated-input"),
        "source_hash": (("latest", "content_hash"), "b" * 64),
        "source_quote": (("latest", "quote"), "PRIVATE_UNRELATED_VALUE"),
        "event_source": (("source", "command", "id"), "unrelated-event-command"),
    }
    path, replacement = replacements[fault]
    target = ledger["events"][-1] if fault == "event_source" else condition
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = replacement


@pytest.mark.parametrize("tool", ["change_item_state", "use_item"])
@pytest.mark.parametrize(
    "fault",
    [
        "skip",
        "custody",
        "missing_ledger",
        "invalid_ledger",
        "missing_condition",
        "wrong_id",
        "item",
        "dimension",
        "value",
        "visual_detail",
        "visibility",
        "source_kind",
        "source_actor",
        "source_operation",
        "source_command",
        "source_input",
        "source_hash",
        "source_quote",
        "missing_event",
        "event_source",
        "duplicate_dimension",
    ],
)
async def test_missing_or_corrupt_property_rolls_back_prefix_and_never_issues_success(
    monkeypatch, tool, fault
):
    async with TestSessionLocal() as db:
        host, _, drafts = await fixture(db)
        draft = drafts["LINA"]
        approve(draft, Take(tool="take_item", item_id="KEY"), request(tool))
        before = deepcopy(host.state.entity_states)
        apply = publication._apply
        diagnostics = []

        async def broken_write(manager, scope, current, preview):
            if current.tool == tool and fault == "skip":
                return
            await apply(manager, scope, current, preview)
            if current.tool == tool:
                states = deepcopy(manager.state.entity_states)
                corrupt(states, fault)
                manager.state.entity_states = states

        monkeypatch.setattr(publication, "_apply", broken_write)
        monkeypatch.setattr(postconditions, "reject", lambda *args, **kw: diagnostics.append(kw))
        with pytest.raises(postconditions.PostconditionViolationError):
            async with db.begin_nested():
                await publication.publish(host, draft, verify_postconditions=True)
        await db.refresh(host.state)
        assert host.state.entity_states == before
        assert (await owners(host))["KEY"] == SCENE
        assert draft.published_results is None
        assert len(diagnostics) == 1 and diagnostics[0]["tool"] == tool
        assert "PRIVATE_" not in str(diagnostics) and "KEY" not in str(diagnostics)


@pytest.mark.parametrize("tool", ["change_item_state", "use_item"])
async def test_repeated_property_commands_reuse_condition_but_verify_each_new_proof(tool):
    async with TestSessionLocal() as db:
        host, observed, drafts = await fixture(db)
        draft = drafts["LINA"]
        approve(draft, Take(tool="take_item", item_id="KEY"), request(tool), request(tool))
        results = await publication.publish(host, draft, verify_postconditions=True)
        assert [row["status"] for row in results] == ["applied"] * 3
        assert results[1]["effect"]["condition_id"] == results[2]["effect"]["condition_id"]
        await db.commit()
        await db.refresh(host.state)
        ledger = read(host.state.entity_states)
        [condition] = ledger.conditions.values()
        assert condition.detail == "PRIVATE_PROPERTY_VALUE"
        assert condition.part == ("surface" if tool == "change_item_state" else "usage")
        assert condition.visibility == ("private" if tool == "change_item_state" else "public")
        assert condition.latest.command.id == results[2]["command_id"]
        assert condition.latest.command.actor_id == "LINA"
        assert condition.latest.message_id == observed.message_id
        assert len(ledger.events) == 2


@pytest.mark.parametrize("tool", ["change_item_state", "use_item"])
async def test_same_value_with_only_an_older_commands_proof_is_not_a_success(monkeypatch, tool):
    async with TestSessionLocal() as db:
        host, _, drafts = await fixture(db)
        draft = drafts["LINA"]
        approve(draft, Take(tool="take_item", item_id="KEY"), request(tool), request(tool))
        apply = publication._apply
        writes = 0

        async def skip_repeat(manager, scope, current, preview):
            nonlocal writes
            if current.tool == tool:
                writes += 1
            if current.tool == tool and writes == 2:
                return
            await apply(manager, scope, current, preview)

        monkeypatch.setattr(publication, "_apply", skip_repeat)
        with pytest.raises(postconditions.PostconditionViolationError):
            async with db.begin_nested():
                await publication.publish(host, draft, verify_postconditions=True)
        await db.refresh(host.state)
        assert (await owners(host))["KEY"] == SCENE
        assert not read(host.state.entity_states).conditions and draft.published_results is None


@pytest.mark.parametrize(
    "extent,expected", [("partial", "Used partly."), ("full", "Used completely.")]
)
async def test_default_use_state_is_verified_without_mechanical_consumption(extent, expected):
    async with TestSessionLocal() as db:
        host, _, drafts = await fixture(db)
        draft = drafts["LINA"]
        approve(
            draft,
            Take(tool="take_item", item_id="KEY"),
            Use(tool="use_item", item_id="KEY", extent=extent),
        )
        results = await publication.publish(host, draft, verify_postconditions=True)
        assert results[-1]["status"] == "applied"
        [condition] = read(host.state.entity_states).conditions.values()
        assert condition.part == "usage" and condition.detail == expected
        assert condition.visibility == "public" and (await owners(host))["KEY"] == "LINA"


async def test_interaction_remains_an_attempt_without_requiring_the_target_to_change():
    async with TestSessionLocal() as db:
        host, _, drafts = await fixture(db)
        draft = drafts["LINA"]
        approve(draft, Interact(tool="interact", target_id="SECOND", action="Offer a greeting."))
        before = deepcopy(host.state.entity_states)
        [result] = await publication.publish(host, draft, verify_postconditions=True)
        assert result["status"] == "attempted"
        assert host.state.entity_states == before
