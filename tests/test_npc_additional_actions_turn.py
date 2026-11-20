"""Chosen final additions share the existing integrated command publication owners."""

import json
from copy import deepcopy

import pytest

from backend.engine.chpm.state import load
from backend.engine.clothing.visuals import session_objects
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.npc_actions import preparation, publication
from backend.engine.npc_actions import runtime as command_runtime
from backend.engine.physical_conditions.ledger import read as conditions
from backend.engine.visual_novel.continuity import PLAYER, SCENE, possession_snapshot
from backend.models.chat import ChatMessage
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_native_notebook_loop import call, turn
from tests.test_chpm_native_notebook_turn import initial_payload
from tests.test_chpm_notebook_turn import ACTION, configure, install
from tests.test_chpm_observable_turn import StateRoles

ITEM = "ADDITIONAL_KEY"
DETAIL = "A polished silver surface."
STEPS = [
    {"tool": "take_item", "item_id": ITEM},
    {"tool": "give_item", "item_id": ITEM, "recipient_id": "@player"},
]
PREFIX = {
    "name": "change_item_state",
    "arguments": {
        "item_id": "HIDDEN_RING",
        "dimension": "surface",
        "detail": DETAIL,
        "visibility": "private",
    },
}


class AdditionalRoles(StateRoles):
    def __init__(self, *, enabled=True, fault=None, include=True):
        super().__init__()
        self.enabled, self.fault, self.include = enabled, fault, include
        self.submissions, self.rounds, self.reviews = [], [], []

    async def requests_for(self, body, offered, model):
        self.rounds.append((deepcopy(body), deepcopy(offered)))
        if body["remaining_rounds"]:
            request = PREFIX if self.enabled else {"name": "inspect_self", "arguments": {}}
            return [deepcopy(request)]
        raw = await self.decision(body, model)
        raw["candidates"][raw["choice"]["preferred"]]["intention"] = (
            "Polish my ring, take the key and give it to the traveler, then continue talking."
            if self.enabled
            else "Thank the traveler and continue talking."
        )
        if self.include:
            raw["additional_actions"] = {
                "for_choice": "DEFER" if self.fault == "choice" else raw["choice"]["preferred"],
                "steps": deepcopy(STEPS),
            }
        if self.fault == "unavailable":
            raw["additional_actions"]["steps"][1] = {"tool": "set_pose", "posture": "sitting"}
        self.submissions.append(deepcopy(raw))
        return [{"name": "submit_decision", "arguments": raw}]

    async def simple(self, system, payload, model, **kwargs):
        phase = kwargs.get("phase")
        body = json.loads(payload)
        if phase == "integrated_decision":
            self.chpm_calls.append(phase)
            return json.dumps({"requests": await self.requests_for(body, body["functions"], model)})
        if phase == "proposal_repair":
            self.chpm_calls.append(phase)
            # Keep the deliberately invalid submission invalid if its owner uses
            # the existing bounded repair; do not authorize a corrected new plan.
            return json.dumps({"edits": []})
        if phase == "validation":
            self.reviews.append(deepcopy(body))
        return await super().simple(system, payload, model, **kwargs)

    async def native(self, messages, tools, model, **kwargs):
        self.chpm_calls.append(kwargs["phase"])
        body = initial_payload(messages)
        requests = await self.requests_for(body, tools, model)
        return turn(
            *(
                call(f"chosen-{body['remaining_rounds']}-{index}", row["name"], row["arguments"])
                for index, row in enumerate(requests)
            )
        )


async def seed(db, protocol, *, enabled=True):
    user, state = await configure(
        db,
        workflow="integrated",
        tool_protocol=protocol,
        notebook_enabled=False,
        action_tools=enabled,
        agent_steps=1,
        max_input_chars=64000,
    )
    db.add(
        WorldEntity(
            id=ITEM,
            session_id=state.session_id,
            entity_type="OBJECT",
            name="Brass key",
            description="One loose brass key.",
            current_scene_id="START",
            is_portable=True,
        )
    )
    await db.commit()
    return user, state


def observe(monkeypatch):
    drafts, published = {}, []
    capture, publish = preparation.capture, command_runtime.publish_turn

    async def captured(*args, **kwargs):
        result = await capture(*args, **kwargs)
        drafts.update(result)
        return result

    async def completed(manager, current):
        await publish(manager, current)
        published.append(current)
        draft = current.action_drafts.get("LINA")
        if draft is None or not draft.approved:
            return
        original = deepcopy(current.action_outcomes)
        before = deepcopy((manager.state.entity_states, manager.avatar.inventory))
        assert await publication.publish(manager, draft) == original["LINA"]
        await publish(manager, current)
        assert current.action_outcomes == original
        assert (manager.state.entity_states, manager.avatar.inventory) == before

    monkeypatch.setattr(preparation, "capture", captured)
    monkeypatch.setattr(command_runtime, "publish_turn", completed)
    return drafts, published


def final_contract(roles):
    body, offered = roles.rounds[-1]
    assert body["remaining_rounds"] == 0
    functions = [item.get("function", item) for item in offered]
    assert [item["name"] for item in functions] == ["submit_decision"]
    return functions[0]["parameters"]


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_final_additions_append_once_to_the_same_draft_and_persist(monkeypatch, protocol):
    roles = AdditionalRoles()
    install(monkeypatch, roles)
    drafts, published = observe(monkeypatch)
    async with TestSessionLocal() as db:
        user, state = await seed(db, protocol)
        user_id, session_id = user.id, state.session_id
        manager, events = await run(db, user, ACTION)

        assert any(event.startswith("event: final") for event in events), "".join(events)
        assert not any(event.startswith("event: error") for event in events)
        assert len(roles.submissions) == len(published) == 1
        assert "additional_actions" in final_contract(roles)["properties"]
        draft = drafts["LINA"]
        assert draft.approved
        assert [request.tool for request in draft.requests] == [
            "change_item_state",
            "take_item",
            "give_item",
        ]
        outcomes = published[0].action_outcomes["LINA"]
        assert [row["status"] for row in outcomes] == ["applied"] * 3
        assert [row["tool"] for row in outcomes] == [request.tool for request in draft.requests]
        for field in ("operation_id", "command_id", "event_id"):
            assert len({row[field] for row in outcomes}) == 3
        assert len({row["attempt_id"] for row in outcomes}) == 1
        assert [row["index"] for row in outcomes] == [0, 1, 2]
        assert outcomes[1]["effect"]["source_owner"] == SCENE
        assert outcomes[2]["effect"]["destination_owner"] == PLAYER
        assert load(manager.state).usage.calls == 4
        assert roles.chpm_calls == [
            "perception",
            "integrated_decision",
            "integrated_decision",
            "validation",
        ]
        assert roles.reviews[0]["contract"]["LINA"]["authoritative_command_outcomes"]

    async with TestSessionLocal() as db:
        user = await db.get(User, user_id)
        manager = GameTurnManager(db, session_id, user)
        assert await manager.initialize()
        snapshot = possession_snapshot(manager, await session_objects(db, session_id))
        assert snapshot.owners[ITEM] == PLAYER
        assert sum(row.get("id") == ITEM for row in manager.avatar.inventory) == 1
        records = list(conditions(manager.state.entity_states).conditions.values())
        assert [(row.target_id, row.part, row.detail) for row in records] == [
            ("HIDDEN_RING", "surface", DETAIL)
        ]
        assert records[0].latest.kind == "command"
        decision = load(manager.state).actors["LINA"]
        assert [row.status for row in decision.last_publication.operations] == ["applied"] * 3
        assert await db.get(ChatMessage, decision.reply_id) is not None


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("fault", ["choice", "unavailable"])
async def test_invalid_additions_cannot_extend_or_approve_the_existing_draft(
    monkeypatch, protocol, fault
):
    roles = AdditionalRoles(fault=fault)
    install(monkeypatch, roles)
    drafts, published = observe(monkeypatch)
    async with TestSessionLocal() as db:
        user, state = await seed(db, protocol)
        before = deepcopy((load(state), conditions(state.entity_states)))
        manager, events = await run(db, user, ACTION)

        assert any(event.startswith("event: error") for event in events), "".join(events)
        assert not any(event.startswith(("event: final", "event: chunk")) for event in events)
        assert not published and len(roles.submissions) == 1
        assert "additional_actions" in final_contract(roles)["properties"]
        draft = drafts["LINA"]
        assert not draft.approved and draft.published_results is None
        assert [request.tool for request in draft.requests] == ["change_item_state"]
        assert len(draft.receipts) == len(draft.operations) == 1
        await db.refresh(state)
        assert (load(state), conditions(state.entity_states)) == before
        reloaded = GameTurnManager(db, state.session_id, user)
        assert await reloaded.initialize()
        snapshot = possession_snapshot(reloaded, await session_objects(db, state.session_id))
        assert snapshot.owners[ITEM] == SCENE


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("include", [False, True])
async def test_disabled_actions_keep_the_previous_terminal_contract(monkeypatch, protocol, include):
    roles = AdditionalRoles(enabled=False, include=include)
    install(monkeypatch, roles)
    drafts, published = observe(monkeypatch)
    async with TestSessionLocal() as db:
        user, state = await seed(db, protocol, enabled=False)
        manager, events = await run(db, user, ACTION)

        expected = "event: error" if include else "event: final"
        assert any(event.startswith(expected) for event in events), "".join(events)
        assert "additional_actions" not in final_contract(roles)["properties"]
        assert not drafts
        assert all(not current.action_outcomes for current in published)
        await db.refresh(state)
        assert not conditions(state.entity_states).conditions
        reloaded = GameTurnManager(db, state.session_id, user)
        assert await reloaded.initialize()
        snapshot = possession_snapshot(reloaded, await session_objects(db, state.session_id))
        assert snapshot.owners[ITEM] == SCENE
        if not include:
            assert load(state).usage.calls == 4
