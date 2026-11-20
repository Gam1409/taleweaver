"""Actual command outcomes must fit review admission before narrator dispatch."""

import json
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.engine.chpm import inference, rendering
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load
from backend.engine.npc_actions import runtime as command_runtime
from backend.engine.physical_conditions.ledger import read
from backend.engine.turn_replay.snapshot import capture
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import LocalFailureRoles, install
from tests.test_chpm_notebook_turn import ACTION
from tests.test_vn_turn_integration import seed_vn

ACTORS = ("LINA", "KEEPER_B", "KEEPER_C", "KEEPER_D", "KEEPER_E")
DETAIL = ("A stable descriptive mark with a smooth surface. " * 8)[:320]
SMALL_INPUT_CAP = 34500


class PropertyRoles(LocalFailureRoles):
    def __init__(self):
        super().__init__()
        self.narrator_calls = 0
        self.reply_limit = 4096

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") != "integrated_decision":
            return await super().simple(system, payload, model, **kwargs)
        supplied = json.loads(payload)
        round_index = len(supplied["previous_lookups"])
        if round_index < 3:
            requests = [
                {
                    "name": "change_item_state",
                    "arguments": {
                        "item_id": "TOKEN_" + supplied["actor_id"],
                        "dimension": f"surface{round_index * 2 + offset}",
                        "detail": DETAIL,
                    },
                }
                for offset in range(2)
            ]
        else:
            requests = [
                {"name": "submit_decision", "arguments": json.loads(self.propose(supplied))}
            ]
        return json.dumps({"requests": requests})

    def review(self, supplied):
        self.reviews.append(supplied)
        return json.dumps(
            {
                "matches": True,
                "evidence": [
                    {
                        "actor_id": actor,
                        "passage_id": next(
                            key for key, text in supplied["passages"].items() if f"{actor}:" in text
                        ),
                    }
                    for actor in supplied["controlled_actor_ids"]
                ],
            }
        )

    async def stream(self, *args, **kwargs):
        self.prompts.append((args, kwargs))
        self.narrator_calls += 1
        speech = "\n".join(f"{actor}: «Записи готовы.»" for actor in ACTORS) + "\n"
        text = (speech + "За окном продолжал идти дождь. " * 200)[: self.reply_limit]

        async def chunks():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=text))])

        return chunks()


async def seed(db, input_cap, policy):
    user, _, state, _ = await seed_vn(db)
    original = await db.scalar(
        select(WorldEntity).where(
            WorldEntity.session_id == state.session_id, WorldEntity.id == "LINA"
        )
    )
    for identifier in ACTORS:
        actor = (
            original
            if identifier == "LINA"
            else WorldEntity(
                id=identifier,
                session_id=state.session_id,
                entity_type="NPC",
                current_scene_id="START",
            )
        )
        actor.name = identifier
        actor.description = "An adult record keeper."
        actor.character = "Values accurate records."
        actor.goal = "Keep records."
        actor.inventory = [{"id": "TOKEN_" + identifier, "name": "Token " + identifier}]
        actor.age_years = 30
        actor.visual_profile = {"appearance": {"age_years": 30}, "worn": []}
        if identifier != "LINA":
            db.add(actor)
    configured = Settings(
        mode="live",
        workflow="integrated",
        action_tools=True,
        actor_ids=list(ACTORS),
        max_active_npcs=len(ACTORS),
        agent_steps=3,
        max_calls_per_turn=25,
        max_input_chars=input_cap,
        tool_protocol="json",
        failure_policy=policy,
        max_output_tokens=4096,
    )
    state.entity_states = {
        **state.entity_states,
        KEY: KernelState(settings=configured).model_dump(),
    }
    await db.commit()
    return user, state


def observe(monkeypatch, roles):
    admissions, preflights, publications = [], [], []
    reserve = inference.reserve
    preflight = rendering.preflight
    publish = command_runtime.publish_turn

    def reserved(settings, usage, size):
        entry = {
            "size": size,
            "input_cap": settings.max_input_chars,
            "call_cap": settings.max_calls_per_turn,
            "before_narration": roles.narrator_calls == 0,
            "admitted": False,
        }
        admissions.append(entry)
        reserve(settings, usage, size)
        entry["admitted"] = True

    def checked(turn):
        entry = {
            "outcomes": sum(map(len, turn.action_outcomes.values())),
            "contract_size": turn.initial.settings.max_input_chars - rendering._review_room(turn),
            "passed": False,
        }
        preflights.append(entry)
        preflight(turn)
        entry["passed"] = True
        roles.reply_limit = turn.reply_character_budget

    async def published(manager, turn):
        await publish(manager, turn)
        publications.extend(
            deepcopy(outcome) for outcomes in turn.action_outcomes.values() for outcome in outcomes
        )

    monkeypatch.setattr(inference, "reserve", reserved)
    monkeypatch.setattr(rendering, "preflight", checked)
    monkeypatch.setattr(command_runtime, "publish_turn", published)
    return admissions, preflights, publications


async def exercise(monkeypatch, input_cap, policy):
    roles = PropertyRoles()
    install(monkeypatch, roles)
    admissions, preflights, publications = observe(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed(db, input_cap, policy)
        before = await capture(db, state.session_id)
        _, events = await run(db, user, ACTION)
        await db.refresh(state)
        after = await capture(db, state.session_id)
        conditions = list(read(state.entity_states).conditions.values())
        result = {
            "roles": roles,
            "admissions": admissions,
            "preflights": preflights,
            "publications": publications,
            "events": events,
            "before": before,
            "after": after,
            "conditions": conditions,
            "kernel": load(state),
        }
    return result


def assert_cognitive_admission(result, input_cap):
    admissions = result["admissions"]
    cognition = [entry for entry in admissions if entry["before_narration"]]
    assert len(cognition) == 21  # Shared perception and four rounds for each of five NPCs.
    assert all(entry["admitted"] and entry["size"] <= input_cap for entry in cognition)
    assert all(entry["input_cap"] == input_cap and entry["call_cap"] == 25 for entry in admissions)
    assert sum(entry["admitted"] for entry in admissions) <= 25
    assert len(result["publications"]) == 30
    assert all(entry["status"] == "applied" for entry in result["publications"])
    assert result["preflights"][0]["outcomes"] == 0 and result["preflights"][0]["passed"]


@pytest.mark.asyncio
async def test_sufficient_review_budget_publishes_all_command_effects_and_reviewed_psychology(
    monkeypatch,
):
    result = await exercise(monkeypatch, 64000, "strict")
    assert_cognitive_admission(result, 64000)
    assert any(event.startswith("event: final") for event in result["events"])
    assert not any(event.startswith("event: error") for event in result["events"])
    assert len(result["conditions"]) == 30
    assert all(condition.latest.kind == "command" for condition in result["conditions"])
    assert set(result["kernel"].actors) == set(ACTORS)
    assert not result["kernel"].usage.simplified
    assert result["roles"].narrator_calls == len(result["roles"].reviews) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["strict", "continue"])
async def test_actual_outcomes_exceeding_review_budget_are_handled_before_narration(
    monkeypatch, policy
):
    result = await exercise(monkeypatch, SMALL_INPUT_CAP, policy)
    assert_cognitive_admission(result, SMALL_INPUT_CAP)
    assert result["roles"].reviews == []
    assert result["preflights"][-1]["outcomes"] == 30
    assert not result["preflights"][-1]["passed"]
    assert result["preflights"][-1]["contract_size"] > SMALL_INPUT_CAP
    if policy == "strict":
        assert result["roles"].narrator_calls == 0
        assert any(event.startswith("event: error") for event in result["events"])
        assert not any(
            event.startswith(("event: chunk", "event: final")) for event in result["events"]
        )
        for key in ("avatar", "tables"):
            assert result["after"][key] == result["before"][key]
        assert (
            result["after"]["state"]["entity_states"] == result["before"]["state"]["entity_states"]
        )
        assert result["conditions"] == []
        return
    assert result["roles"].narrator_calls == 1
    assert any(event.startswith("event: final") for event in result["events"])
    assert not any(event.startswith("event: error") for event in result["events"])
    assert len(result["conditions"]) == 30
    assert all(condition.latest.kind == "command" for condition in result["conditions"])
    assert result["kernel"].usage.simplified
    assert result["kernel"].usage.fallback_reason == "analysis_failed"
    assert not result["kernel"].actors and not result["kernel"].minds
