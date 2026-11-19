"""Two-phase decisions through a real VN turn, owner publication and SQL reload."""

import json
from copy import deepcopy

import pytest

from backend.engine.chpm.state import KEY, load
from backend.engine.clothing.visuals import session_objects
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.visual_novel.continuity import SCENE, possession_snapshot
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.chpm_reference_fixture import proposal
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_kernel import preferred_choice, wire_proposal
from tests.test_chpm_local_failure_turn import LocalFailureRoles, install, seed_pair
from tests.test_chpm_native_notebook_loop import call, turn
from tests.test_chpm_native_notebook_turn import initial_payload
from tests.test_npc_additional_actions_turn import observe

CUP = "COPPER_CUP"
TAKE = {"tool": "take_item", "item_id": CUP}
GIVE = {"tool": "give_item", "item_id": CUP, "recipient_id": "@player"}
PLAYER = "I put my own backpack away and ask what each of you thinks about the parcel."


class CupRoles(LocalFailureRoles):
    def __init__(self, steps, *, wrong_once=False):
        super().__init__()
        self.steps, self.wrong_once = steps, wrong_once
        self.choices, self.executions = [], []

    def for_role(self, *args, **kwargs):
        model = super().for_role(*args, **kwargs)
        model.aexecute_tool_turn = self.native
        return model

    def answer(self, payload, functions, phase, kwargs):
        offered = {row["name"]: row for row in (item.get("function", item) for item in functions)}
        if phase == "npc_execution":
            self.executions.append((set(offered), kwargs.get("tool_choice")))
            steps = deepcopy(self.steps)
            if self.wrong_once and len(self.executions) == 1:
                # A malformed second command must not leave a take staged on retry.
                steps[-1]["item_id"] = "UNRELATED"
            return [(step.pop("tool"), step) for step in steps]

        self.choices.append((payload, offered))
        result = wire_proposal()
        result["candidates"]["REFUSE"] = result["candidates"].pop("CONTINUE")
        result["candidates"]["REFUSE"]["intention"] = (
            "Decline to open the parcel and act on my own choice about the cup."
        )
        result["choice"] = preferred_choice(payload, preferred="REFUSE")
        result["physical_intent"] = {"mode": "act" if self.steps else "none", "steps": self.steps}
        return [("submit_decision", proposal(result, payload))]

    async def native(self, messages, tools, model, **kwargs):
        requests = self.answer(initial_payload(messages), tools, kwargs["phase"], kwargs)
        return turn(
            *(
                call(f"cup-{len(self.choices)}-{len(self.executions)}-{index}", name, arguments)
                for index, (name, arguments) in enumerate(requests)
            )
        )

    async def simple(self, system, payload, model, **kwargs):
        body = json.loads(payload)
        if "functions" not in body:
            return await super().simple(system, payload, model, **kwargs)
        requests = self.answer(body, body["functions"], kwargs["phase"], kwargs)
        return json.dumps({"requests": [{"name": n, "arguments": a} for n, a in requests]})


async def seed(db, protocol, *, pair):
    user, state = await seed_pair(db, policy="strict")
    config = load(state)
    config.settings = type(config.settings).model_validate(
        {
            **config.settings.model_dump(),
            "npc_decision_mode": "two_phase",
            "action_tools": True,
            "workflow": "integrated",
            "actor_ids": ["LINA", "MILA"] if pair else ["LINA"],
            "agent_steps": 1,
            "tool_protocol": protocol,
            "max_calls_per_turn": 16,
            "max_input_chars": 64000,
        }
    )
    state.entity_states = {**state.entity_states, KEY: config.model_dump()}
    db.add(
        WorldEntity(
            id=CUP,
            session_id=state.session_id,
            entity_type="OBJECT",
            name="Copper cup",
            description="A single loose cup.",
            current_scene_id="START",
            is_portable=True,
        )
    )
    await db.commit()
    return user, state


async def reload(db, session_id, user_id):
    user = await db.get(User, user_id)
    manager = GameTurnManager(db, session_id, user)
    assert await manager.initialize()
    rows = await session_objects(db, session_id)
    return user, manager, possession_snapshot(manager, rows)


def assert_committed(events):
    assert not any(line.startswith("event: error") for line in events), "".join(events)
    assert any(line.startswith("event: final") for line in events)


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_competing_refusals_publish_one_cup_then_recall_only_own_result(
    monkeypatch, protocol
):
    roles = CupRoles([TAKE])
    install(monkeypatch, roles)
    _, publications = observe(monkeypatch)
    async with TestSessionLocal() as db:
        user, state = await seed(db, protocol, pair=True)
        user_id, session_id = user.id, state.session_id
        manager, events = await run(db, user, PLAYER)
        assert_committed(events)
        first = publications[-1].action_outcomes
        assert first["LINA"][0]["status"] == "applied"
        assert first["MILA"][0]["status"] == "blocked"
        assert first["MILA"][0]["reason_code"] == "unavailable_entity"
        assert all(
            load(manager.state).actors[actor].last_publication.execution.status == "staged"
            for actor in first
        )
        assert all(load(manager.state).actors[actor].selected.kind == "REFUSE" for actor in first)
        assert len(roles.executions) == len(roles.choices) == 2
        for _, offered in roles.choices:
            assert set(offered) == {"submit_decision"}
            assert "physical_intent" in offered["submit_decision"]["parameters"]["required"]
        assert all(names == {"take_item"} for names, _ in roles.executions)
        if protocol == "native":
            assert all(choice == "required" for _, choice in roles.executions)
        assert load(manager.state).usage.calls == 6  # perception, two choices/actions, review

    async with TestSessionLocal() as db:
        user, manager, snapshot = await reload(db, session_id, user_id)
        assert snapshot.owners[CUP] == "LINA"
        assert CUP not in [entry["id"] for entry in manager.avatar.inventory]
        roles.steps = []
        _, events = await run(db, user, "I wait for you both to speak.")
        assert_committed(events)
        assert len(roles.executions) == 2
        assert publications[-1].action_outcomes == {"LINA": [], "MILA": []}
        for body, _ in roles.choices[2:]:
            actor = body["actor_id"]
            assert (
                body["previous_action_results_not_current_state"]["execution"]["status"] == "staged"
            )
            prior = body["previous_action_results_not_current_state"]["operations"]
            assert [(item["operation_id"], item["status"]) for item in prior] == [
                (first[actor][0]["operation_id"], first[actor][0]["status"])
            ]


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_wrong_second_operand_can_be_repaired_without_a_duplicate_take(monkeypatch, protocol):
    roles = CupRoles([TAKE, GIVE], wrong_once=True)
    install(monkeypatch, roles)
    drafts, publications = observe(monkeypatch)
    async with TestSessionLocal() as db:
        user, state = await seed(db, protocol, pair=False)
        user_id, session_id = user.id, state.session_id
        manager, events = await run(db, user, PLAYER)
        assert_committed(events)
        assert len(roles.choices) == 1 and len(roles.executions) == 2
        assert all(names == {"take_item", "give_item"} for names, _ in roles.executions)
        assert load(manager.state).usage.proposal_repairs == 1
        assert [row.tool for row in drafts["LINA"].requests] == ["take_item", "give_item"]
        rows = publications[-1].action_outcomes["LINA"]
        assert [row["status"] for row in rows] == ["applied", "applied"]
        assert rows[0]["effect"]["source_owner"] == SCENE
        assert rows[0]["operation_id"] != rows[1]["operation_id"]

    async with TestSessionLocal() as db:
        _, manager, snapshot = await reload(db, session_id, user_id)
        assert snapshot.owners[CUP] == "__player__"
        assert sum(item["id"] == CUP for item in manager.avatar.inventory) == 1


async def test_rejected_scene_rolls_back_owner_and_receipt_before_another_turn(monkeypatch):
    roles = CupRoles([TAKE])
    roles.reject_reviews = 2
    install(monkeypatch, roles)
    _, publications = observe(monkeypatch)
    async with TestSessionLocal() as db:
        user, state = await seed(db, "json", pair=False)
        user_id, session_id = user.id, state.session_id
        _, events = await run(db, user, PLAYER)
        assert any(line.startswith("event: error") for line in events)
        assert not any(line.startswith(("event: final", "event: chunk")) for line in events)
        first = publications[-1].action_outcomes["LINA"][0]
        assert first["status"] == "applied"

    async with TestSessionLocal() as db:
        user, manager, snapshot = await reload(db, session_id, user_id)
        assert snapshot.owners[CUP] == SCENE
        assert not load(manager.state).actors
        _, events = await run(db, user, PLAYER)
        assert_committed(events)
        last = publications[-1].action_outcomes["LINA"][0]
        assert last["status"] == "applied"
        assert first["attempt_id"] != last["attempt_id"]
        assert first["operation_id"] != last["operation_id"]
        assert "previous_action_results_not_current_state" not in roles.choices[-1][0]
