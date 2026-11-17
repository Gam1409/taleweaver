"""An approved empty plan stays explicit through the existing prose consumers."""

import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.engine import turn_controls
from backend.engine.chpm import continuation, runtime
from backend.engine.chpm.state import KEY, load
from backend.engine.npc_actions import control, instructions, reconciliation
from backend.engine.npc_actions import runtime as command_runtime
from backend.engine.npc_actions.contracts import Interact, Take
from backend.engine.npc_actions.runtime import publish_turn
from backend.engine.physical_conditions.ledger import read
from backend.engine.visual_novel.config import read_settings, write_settings
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.npc_control_support import bind_observation
from tests.test_chpm_host_turn import run
from tests.test_chpm_native_notebook_loop import call, turn
from tests.test_chpm_native_notebook_turn import initial_payload
from tests.test_chpm_notebook_turn import ACTION, install
from tests.test_chpm_observable_turn import StateRoles, prepare
from tests.test_npc_action_lifecycle import controller_turn
from tests.test_npc_action_movement import movement_fixture
from tests.test_npc_action_publication import fixture as publication_fixture
from tests.test_vn_turn_integration import NARRATION

EMPTY_GUIDANCE = "An empty list means no command was executed"


class EmptyPlanRoles(StateRoles):
    def __init__(self, *, repair=False):
        super().__init__()
        self.repair = repair
        self.reviews, self.repairs, self.offered = [], [], []

    async def decision(self, body, model):
        proposal = await super().decision(body, model)
        proposal["candidates"]["CONTINUE"]["intention"] = "Polish the ring and crouch."
        return proposal

    async def simple(self, system, payload, model, **kwargs):
        phase = kwargs.get("phase")
        supplied = json.loads(payload)
        if phase == "integrated_decision":
            self.chpm_calls.append(phase)
            self.offered.append(supplied["functions"])
            return json.dumps(
                {
                    "requests": [
                        {
                            "name": "submit_decision",
                            "arguments": await self.decision(supplied, model),
                        }
                    ]
                }
            )
        if phase == "validation":
            self.reviews.append((system, supplied))
            if self.repair and len(self.reviews) == 1:
                self.chpm_calls.append(phase)
                return json.dumps(
                    {
                        "review_scope": supplied["review_scope"],
                        "matches": False,
                        "rejections": [{"reason_code": "world", "actor_id": "LINA"}],
                    }
                )
        if phase == "repair":
            self.chpm_calls.append(phase)
            self.repairs.append((system, supplied))
            return NARRATION
        return await super().simple(system, payload, model, **kwargs)

    async def native(self, messages, tools, model, **kwargs):
        self.chpm_calls.append(kwargs["phase"])
        self.offered.append(tools)
        return turn(
            call(
                "empty-decision",
                "submit_decision",
                await self.decision(initial_payload(messages), model),
            )
        )


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("repair", [False, True])
async def test_empty_approved_plan_reaches_narrator_review_and_existing_repair(
    monkeypatch, protocol, repair
):
    roles = EmptyPlanRoles(repair=repair)
    install(monkeypatch, roles)
    prepared = []
    publish = command_runtime.publish_turn

    async def published(manager, current):
        await publish(manager, current)
        prepared.append(current)

    monkeypatch.setattr(command_runtime, "publish_turn", published)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", protocol, False)
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        write_settings(state, read_settings(state).model_copy(update={"scene_staging": True}))
        await db.commit()
        facts = read(state.entity_states).model_dump(exclude={"last_check"})

        manager, events = await run(db, user, ACTION)

        assert any(event.startswith("event: final") for event in events), "".join(events)
        current = prepared[0]
        draft = current.action_drafts["LINA"]
        assert draft.approved and not draft.requests and not draft.operations
        assert draft.published_results == []
        assert current.action_outcomes == {"LINA": []}
        assert read(manager.state.entity_states).model_dump(exclude={"last_check"}) == facts
        assert "change_item_state" in str(roles.offered)
        assert "set_pose" in str(roles.offered)
        assert EMPTY_GUIDANCE in str(roles.prompts)
        assert '"authoritative_command_outcomes":[]' in str(roles.prompts)
        for system, supplied in roles.reviews:
            assert EMPTY_GUIDANCE in system
            assert supplied["contract"]["LINA"]["authoritative_command_outcomes"] == []
            assert not supplied["contract"]["LINA"].get("rejected_command_previews")
        assert len(roles.repairs) == int(repair)
        for system, supplied in roles.repairs:
            assert EMPTY_GUIDANCE in system
            assert supplied["dialogue_contract"]["LINA"]["authoritative_command_outcomes"] == []
        assert load(manager.state).usage.calls == (5 if repair else 3)

        assert runtime.current(manager) is None
        assert reconciliation.context(manager) is None


@pytest.mark.parametrize("changed", [False, True])
async def test_empty_plan_is_final_only_after_current_approved_publication(changed):
    async with TestSessionLocal() as db:
        manager, _, _, observed, draft = await movement_fixture(db)
        bind_observation(manager, observed)
        current = controller_turn(manager, observed, draft)
        draft.approved = False
        await publish_turn(manager, current)
        assert current.action_outcomes == {} and draft.published_results is None

        draft.approved = True
        if changed:
            draft.scope = replace(draft.scope, input_revision="other-revision")
        await publish_turn(manager, current)

        assert current.action_outcomes == ({} if changed else {"LINA": []})
        assert draft.published_results == (None if changed else [])
        if not changed:
            first = deepcopy(current.action_outcomes)
            await publish_turn(manager, current)
            assert current.action_outcomes == first
            captured = runtime.Turn(
                current.initial,
                observed.message_id,
                action_drafts=current.action_drafts,
                action_outcomes=current.action_outcomes,
                control=turn_controls.scope(manager, "narration_review", observation=observed),
            )
            manager._chpm_turn = captured
            continuation.activate(captured, "review_unavailable")
            assert EMPTY_GUIDANCE in continuation.contract(captured)
            assert reconciliation.context(manager) == {
                "controlled_actor_ids": ["LINA"],
                "outcomes": {"LINA": []},
            }
            turn_controls.close(manager)
            assert runtime.current(manager) is None
            assert reconciliation.context(manager) is None


@pytest.mark.parametrize("status", ["applied", "blocked", "attempted"])
async def test_empty_actor_context_preserves_other_published_results(status):
    async with TestSessionLocal() as db:
        manager, observed, drafts = await publication_fixture(db)
        bind_observation(manager, observed)
        current = controller_turn(manager, observed, drafts["LINA"])
        current.initial.settings.actor_ids = ["LINA", "SECOND"]
        manager.state.entity_states = {
            **manager.state.entity_states,
            KEY: current.initial.model_dump(),
        }
        current.action_drafts = drafts
        current.decisions["SECOND"] = SimpleNamespace(observation=observed)
        current.control = turn_controls.scope(manager, "narration_review", observation=observed)
        request = (
            Interact(tool="interact", target_id="LINA", action="Offer to help.")
            if status == "attempted"
            else Take(tool="take_item", item_id="KEY")
        )
        assert drafts["SECOND"].execute(request)["status"] == "staged"
        drafts["SECOND"].approved = True
        if status == "blocked":
            manager.state.entity_states = {
                **manager.state.entity_states,
                "KEY": {"is_hidden": True},
            }

        await publish_turn(manager, current)

        supplied = control.model_outcomes(current)
        assert supplied["LINA"] == []
        assert supplied["SECOND"][0]["status"] == status
        assert EMPTY_GUIDANCE in instructions.for_outcomes(supplied)
        assert EMPTY_GUIDANCE in instructions.resolution_instructions(supplied)
        nonempty = {"SECOND": supplied["SECOND"]}
        assert instructions.for_outcomes(nonempty) == instructions.NARRATION
        assert instructions.resolution_instructions(nonempty) == instructions.RESOLUTION_CHRONOLOGY


@pytest.mark.parametrize(
    "changes",
    [{"mode": "off"}, {"mode": "shadow"}, {"action_tools": False}, {"actor_ids": ["OTHER"]}],
)
async def test_control_settings_changed_during_source_check_cannot_publish_empty_authority(
    monkeypatch, changes
):
    async with TestSessionLocal() as db:
        manager, _, _, observed, draft = await movement_fixture(db)
        bind_observation(manager, observed)
        current = controller_turn(manager, observed, draft)
        check = command_runtime._current_input

        async def changed_settings(host, observation):
            valid = await check(host, observation)
            states = deepcopy(host.state.entity_states)
            states[KEY]["settings"].update(changes)
            host.state.entity_states = states
            return valid

        monkeypatch.setattr(command_runtime, "_current_input", changed_settings)
        await publish_turn(manager, current)

        assert current.action_outcomes == {} and draft.published_results is None


async def test_scene_changed_during_saved_input_lookup_cannot_publish_empty_authority(monkeypatch):
    async with TestSessionLocal() as db:
        manager, _, _, observed, draft = await movement_fixture(db)
        bind_observation(manager, observed)
        current = controller_turn(manager, observed, draft)
        scalar = db.scalar

        async def changed_scene(*args, **kwargs):
            row = await scalar(*args, **kwargs)
            manager.state.current_scene_id = "ANNEX"
            return row

        monkeypatch.setattr(db, "scalar", changed_scene)

        await publish_turn(manager, current)

        assert manager.state.current_scene_id == "ANNEX"
        assert current.action_outcomes == {} and draft.published_results is None


@pytest.mark.parametrize("change", ["contents", "revision", "role", "active_input", "attempt"])
async def test_stale_empty_plan_never_becomes_a_current_publication(change):
    async with TestSessionLocal() as db:
        manager, _, _, observed, draft = await movement_fixture(db)
        bind_observation(manager, observed)
        current = controller_turn(manager, observed, draft)
        message = await db.get(ChatMessage, observed.message_id)
        if change == "contents":
            message.content += " Updated."
        if change == "revision":
            message.revision_id = "changed-revision"
        if change == "role":
            message.role = "assistant"
        if change == "active_input":
            manager._vn_player_message_id = "another-input"
        if change == "attempt":
            turn_controls.begin(manager)

        await publish_turn(manager, current)

        assert current.action_outcomes == {} and draft.published_results is None
