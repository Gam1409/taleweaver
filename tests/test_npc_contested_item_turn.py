"""Independent NPC plans share owner adjudication and retain their own final feedback."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.chpm.schema import Settings
from backend.engine.chpm.state import KEY, load
from backend.engine.clothing.visuals import session_objects
from backend.engine.npc_actions import runtime as action_runtime
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.chpm_reference_fixture import tool_turn as reference_turn
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import LocalFailureRoles, install, seed_pair
from tests.test_chpm_native_notebook_loop import call, turn
from tests.test_chpm_native_notebook_turn import initial_payload, tool_results

ITEM = "CONTESTED_CUP"
ACTORS = ("LINA", "MILA")
PLANS = {
    "LINA": "LINA_PRIVATE_PLAN: examine the cup myself and offer Mila a look without deciding her reply.",
    "MILA": "MILA_PRIVATE_PLAN: take the cup for my own inspection and then give it to the traveler.",
}
STORY = (
    "Лина: «Кружка пока у меня. Хочешь посмотреть?»\n"
    "Мила: «Я сама хотела её проверить. Пока ничего не обещаю.»"
)
FOLLOW_UP = (
    "Лина: «Я поставила кружку на стол; никто не обязан её брать.»\n"
    "Мила: «Покажешь, как устроена эта ручка? Я ещё решу, что делать дальше.»"
)


def received_contract(text):
    decoder = json.JSONDecoder()
    offset = 0
    while (start := text.find("{", offset)) >= 0:
        offset = start + 1
        try:
            candidate, length = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if "current_execution_frame" in candidate and all(actor in candidate for actor in ACTORS):
            return candidate
        offset = start + length
    raise AssertionError("The actual narrator request omitted the execution contract.")


class ContentionRoles(LocalFailureRoles):
    def __init__(self, *, false_success=False):
        super().__init__()
        self.initiate_then_continue = True
        self.false_success = false_success
        self.first_input = None
        self.inputs, self.contracts, self.writer_texts = [], [], []

    def for_role(self, *args, **kwargs):
        model = super().for_role(*args, **kwargs)
        model.aexecute_tool_turn = self.reference_native
        return model

    async def reference_native(self, messages, tools, model, **kwargs):
        return reference_turn(await self.native(messages, tools, model, **kwargs), messages)

    def first_turn(self, body):
        identifier = body["observation"]["message_id"]
        self.first_input = self.first_input or identifier
        return identifier == self.first_input

    def requests_for(self, body, *, has_results):
        first = self.first_turn(body)
        actor = body["actor_id"]
        if has_results:
            raw = json.loads(self.propose(body))
            selected = raw["candidates"][raw["choice"]["preferred"]]
            selected["intention"] = (
                PLANS[actor]
                if first
                else (
                    "Place the cup on the table while preserving Mila's freedom to choose."
                    if actor == "LINA"
                    else "Ask Lina about the cup without assuming her answer."
                )
            )
            return [{"name": "submit_decision", "arguments": raw}]
        self.inputs.append(deepcopy(body))
        if first and actor == "MILA":
            return [
                {"name": "take_item", "arguments": {"item_id": ITEM}},
                {"name": "give_item", "arguments": {"item_id": ITEM, "recipient_id": "@player"}},
            ]
        if first:
            return [
                {"name": "take_item", "arguments": {"item_id": ITEM}},
                {
                    "name": "interact",
                    "arguments": {
                        "target_id": "MILA",
                        "action": "Offer to show the cup; leave her reply unresolved.",
                    },
                },
            ]
        if actor == "LINA":
            return [
                {
                    "name": "put_down_item",
                    "arguments": {"item_id": ITEM, "position": "on the table"},
                }
            ]
        return [
            {
                "name": "interact",
                "arguments": {
                    "target_id": "LINA",
                    "action": "Ask about the cup; leave her reply unresolved.",
                },
            }
        ]

    async def simple(self, system, payload, model, **kwargs):
        phase = kwargs.get("phase")
        if phase == "integrated_decision":
            self.chpm_calls.append(phase)
            body = json.loads(payload)
            return json.dumps(
                {"requests": self.requests_for(body, has_results=bool(body["previous_lookups"]))}
            )
        if phase == "repair":
            self.chpm_calls.append(phase)
            return STORY
        return await super().simple(system, payload, model, **kwargs)

    async def native(self, messages, tools, model, **kwargs):
        self.chpm_calls.append(kwargs["phase"])
        body = initial_payload(messages)
        requests = self.requests_for(body, has_results=bool(tool_results(messages)))
        return turn(
            *(
                call(
                    f"{body['actor_id']}-{len(tool_results(messages))}-{index}",
                    row["name"],
                    row["arguments"],
                )
                for index, row in enumerate(requests)
            )
        )

    async def stream(self, *args, **kwargs):
        text = "\n".join(
            [
                *(entry for entry in args if isinstance(entry, str)),
                *(row.get("content", "") for row in kwargs.get("messages") or []),
            ]
        )
        self.writer_texts.append(text)
        self.contracts.append(received_contract(text))
        return await super().stream(*args, **kwargs)

    @property
    def story(self):
        if len(self.contracts) > 1:
            return FOLLOW_UP
        return (
            "Лина: «Кружка у меня; Мила уже согласилась взять её.»\nМила: «Кружка уже у меня, и я согласилась.»"
            if self.false_success
            else STORY
        )

    def review(self, supplied):
        self.reviews.append(deepcopy(supplied))
        if self.false_success and len(self.reviews) == 1:
            # The model double exercises the existing semantic rejection contract;
            # this does not establish live-model detection of misleading prose.
            return json.dumps(
                {
                    "review_scope": supplied["review_scope"],
                    "matches": False,
                    "rejections": [
                        {"reason_code": "world", "actor_id": "MILA"},
                        {"reason_code": "agency", "actor_id": "LINA"},
                    ],
                }
            )
        names = {"LINA": "Лина:", "MILA": "Мила:"}
        return json.dumps(
            {
                "matches": True,
                "evidence": [
                    {
                        "actor_id": actor,
                        "passage_id": next(
                            key
                            for key, text in supplied["passages"].items()
                            if names[actor] in text
                        ),
                    }
                    for actor in supplied["controlled_actor_ids"]
                ],
            }
        )


async def seed(db, protocol):
    user, state = await seed_pair(db, policy="strict")
    goals = {
        "LINA": "Inspect the cup while keeping my decisions independent.",
        "MILA": "Inspect the cup myself before offering it to the traveler.",
    }
    for actor in (
        await db.scalars(
            select(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.id.in_(ACTORS)
            )
        )
    ).all():
        actor.goal = goals[actor.id]
    db.add(
        WorldEntity(
            id=ITEM,
            session_id=state.session_id,
            entity_type="OBJECT",
            name="Brass cup",
            description="One loose brass cup.",
            current_scene_id="START",
            is_portable=True,
        )
    )
    current = load(state)
    current.settings = Settings(
        mode="live",
        workflow="integrated",
        actor_ids=list(ACTORS),
        action_tools=True,
        agent_steps=2,
        max_calls_per_turn=11,
        max_input_chars=64000,
        tool_protocol=protocol,
        failure_policy="strict",
    )
    state.entity_states = {**state.entity_states, KEY: current.model_dump()}
    await db.commit()
    return user, state


def receipt_rows(contract):
    return {actor: contract[actor]["authoritative_command_outcomes"] for actor in ACTORS}


def assert_shared_outcomes(roles, first):
    assert [row["status"] for row in first["LINA"]] == ["applied", "attempted"]
    assert [row["status"] for row in first["MILA"]] == ["blocked", "skipped_dependency"]
    assert all(not row.get("effect") for row in first["MILA"])
    assert "consent" not in first["LINA"][1]["effect"]
    assert first["LINA"][1]["effect"]["target_id"] == "MILA"
    narrator = roles.contracts[0]
    assert receipt_rows(roles.reviews[0]["contract"]) == receipt_rows(narrator)
    assert narrator["current_execution_frame"]["entities"][ITEM]["owner_id"] == "LINA"
    shared = narrator["current_execution_frame"]["request_control"]
    for actor in ACTORS:
        canonical = {row["operation_id"]: row for row in first[actor]}
        for row in narrator[actor]["authoritative_command_outcomes"]:
            restored = {key: value for key, value in row.items() if key != "request_control_ref"}
            restored.update(
                {
                    key: shared[key]
                    for key in ("attempt_id", "input_id", "input_hash", "input_revision")
                    if key in shared
                }
            )
            assert restored == {
                key: value
                for key, value in canonical[row["operation_id"]].items()
                if not key.startswith("diagnostic_")
            }


def assert_private_feedback(body, first, first_ids):
    actor = body["actor_id"]
    peer = "MILA" if actor == "LINA" else "LINA"
    feedback = body["previous_action_results_not_current_state"]
    assert body["previous_intention"]["selected"]["intention"] == PLANS[actor]
    assert {row["operation_id"] for row in feedback["operations"]} == first_ids[actor]
    assert [row["status"] for row in feedback["operations"]] == [
        row["status"] for row in first[actor]
    ]
    assert not first_ids[peer].intersection(row["operation_id"] for row in feedback["operations"])
    assert PLANS[peer] not in json.dumps(body, ensure_ascii=False)


@pytest.mark.parametrize(
    "protocol,false_success", [("native", False), ("json", False), ("json", True)]
)
async def test_contested_item_outcomes_reach_both_roles_and_next_independent_decisions(
    monkeypatch, protocol, false_success
):
    roles = ContentionRoles(false_success=false_success)
    install(monkeypatch, roles)
    publications = []
    publish = action_runtime.publish_turn

    async def published(host, current):
        if not publications:
            assert set(current.decisions) == set(ACTORS)
            assert all(
                draft.approved and len(draft.requests) == 2
                for draft in current.action_drafts.values()
            )
            assert (
                possession_snapshot(host, await session_objects(host.db, host.game_id)).owners[ITEM]
                == "__scene__"
            )
        await publish(host, current)
        publications.append(deepcopy(current.action_outcomes))

    monkeypatch.setattr(action_runtime, "publish_turn", published)
    async with TestSessionLocal() as db:
        user, state = await seed(db, protocol)
        host, events = await run(
            db, user, "Вы обе замечаете единственную латунную кружку на столе."
        )
        assert any(event.startswith("event: final") for event in events), "".join(events)
        assert not any(event.startswith("event: error") for event in events), "".join(events)
        saved = load(state)
        assert set(saved.actors) == set(ACTORS)
        assert all(saved.actors[actor].selected.kind == "INITIATE" for actor in ACTORS)
        first = publications[0]
        assert_shared_outcomes(roles, first)
        assert (await db.get(ChatMessage, saved.actors["MILA"].reply_id)).content == STORY
        assert saved.usage.calls == (8 if false_success else 6)
        first_ids = {actor: {row["operation_id"] for row in first[actor]} for actor in ACTORS}
        for actor in ACTORS:
            assert any(
                motive.source.subject_id == actor and motive.effect == "supports"
                for motive in saved.actors[actor].candidate_motives["INITIATE"]
            )
            assert first_ids[actor] == {
                row.operation_id for row in saved.actors[actor].last_publication.operations
            }
        state_id, user_id = state.id, user.id
        await db.commit()
    async with TestSessionLocal() as db:
        state = await db.get(SessionState, state_id)
        user = await db.get(User, user_id)
        reloaded = SimpleNamespace(
            state=state, avatar=await db.get(Avatar, state.avatar_id), game_id=state.session_id
        )
        assert (
            possession_snapshot(reloaded, await session_objects(db, state.session_id)).owners[ITEM]
            == "LINA"
        )
        host, events = await run(db, user, "Решайте сами, что хотите делать дальше.")
        assert any(event.startswith("event: final") for event in events), "".join(events)
        assert not any(event.startswith("event: error") for event in events), "".join(events)
        second = publications[1]
        assert [row["tool"] for row in second["LINA"]] == ["put_down_item"]
        assert [row["status"] for row in second["MILA"]] == ["attempted"]
        assert (
            roles.contracts[1]["current_execution_frame"]["entities"][ITEM]["owner_id"]
            == "__scene__"
        )
        assert roles.reviews[-1]["contract"] == roles.contracts[1]
        assert len(roles.reviews) == (3 if false_success else 2)
        for body in roles.inputs[-2:]:
            assert_private_feedback(body, first, first_ids)
        assert load(state).usage.calls == 6
        snapshot = possession_snapshot(host, await session_objects(db, host.game_id))
        assert snapshot.owners[ITEM] == "__scene__"
        assert host.avatar.inventory == []
        assert (
            len(
                (
                    await db.scalars(
                        select(WorldEntity).where(
                            WorldEntity.session_id == host.game_id, WorldEntity.id == ITEM
                        )
                    )
                ).all()
            )
            == 1
        )
