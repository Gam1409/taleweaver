"""The actual narrator policy must agree with per-actor command ownership."""

import hashlib
from types import SimpleNamespace

import pytest

from backend.engine.chpm.state import KEY, load
from backend.engine.npc_actions import instructions
from backend.engine.npc_actions import runtime as action_runtime
from backend.engine.visual_novel.narration import narration_suffix
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import LocalFailureRoles, install
from tests.test_npc_contested_item_turn import ACTORS, ContentionRoles, seed
from tests.test_vn_turn_integration import final_payload

UNSCOPED_COMPLETION = (
    "NPCs may carry out their own feasible actions without a player command or approval:",
    "New completed NPC item actions\nuse the same-turn state check",
    "A movable present NPC may also complete a departure through a known open exit",
    "Small gestures may change a pose within the\nsame place",
)


class EmptyScopeRoles(ContentionRoles):
    def __init__(self):
        super().__init__()
        self.outbound, self.review_systems = [], []

    @property
    def story(self):
        return "Лина: «Хороший вопрос.»\nМила: «Надо подумать.»"

    def requests_for(self, body, *, has_results):
        if not has_results:
            self.inputs.append(body)
            return [{"name": "inspect_scene", "arguments": {}}]
        return super().requests_for(body, has_results=True)

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") == "validation":
            self.review_systems.append(system)
        return await super().simple(system, payload, model, **kwargs)

    async def stream(self, *args, **kwargs):
        self.outbound.append(kwargs["messages"])
        return await LocalFailureRoles.stream(self, *args, **kwargs)


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("controlled", [ACTORS, ("LINA",)])
async def test_empty_publications_select_scoped_policy_in_real_narrator_and_review(
    monkeypatch, protocol, controlled
):
    roles = EmptyScopeRoles()
    install(monkeypatch, roles)
    published = []
    publish = action_runtime.publish_turn

    async def observe_publish(manager, current):
        await publish(manager, current)
        published.append({actor: list(rows) for actor, rows in current.action_outcomes.items()})

    monkeypatch.setattr(action_runtime, "publish_turn", observe_publish)
    async with TestSessionLocal() as db:
        user, state = await seed(db, protocol)
        kernel = load(state)
        kernel.settings.actor_ids = list(controlled)
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
        manager, events = await run(db, user, "Я молча смотрю на кружку, ничего не перемещая.")
        assert final_payload(events)["status"] == "success", "".join(events)
        assert published == [{actor: [] for actor in controlled}]
        assert set(load(manager.state).actors) == set(controlled)
        system = roles.outbound[0][0]["content"]
        outbound = "\n".join(row["content"] for row in roles.outbound[0])
        assert not any(clause in system for clause in UNSCOPED_COMPLETION)
        assert "For NPCs without authoritative_command_outcomes" in system
        assert "Neither speech nor a question is required" in system
        assert "small expressive gestures" in outbound
        assert instructions.EXECUTION in outbound
        assert outbound.count(instructions.EXECUTION) == 1
        assert "Expressive gestures vary presentation, not command-owned fields" in outbound
        assert roles.reviews
        assert all(instructions.EXECUTION in system for system in roles.review_systems)
        assert all(
            "Expressive gestures vary presentation, not command-owned fields" in system
            for system in roles.review_systems
        )
        for review in roles.reviews:
            assert review["controlled_actor_ids"] == list(controlled)
            for actor in controlled:
                assert review["contract"][actor]["authoritative_command_outcomes"] == []
        assert "Never write the player's next unchosen speech" in system
        assert "CURRENT GAME TIME" in system
        assert not (state.entity_states or {}).get("__scene_staging__")


def test_default_suffix_preserves_the_ordinary_policy_exactly():
    state = SimpleNamespace(entity_states={})
    # Off, shadow and ordinary callers retain the same established public contract.
    assert hashlib.sha256(narration_suffix(state).encode()).hexdigest() == (
        "80f1c34c836796ea0437b316aacbd314328c787a5e98d12dceaa85c66f004015"
    )
    assert all(clause in narration_suffix(state) for clause in UNSCOPED_COMPLETION)


def test_controlled_suffix_retains_uncontrolled_actors_and_expressive_freedom():
    state = SimpleNamespace(entity_states={})
    result = narration_suffix(state, command_owned=True)
    assert not any(clause in result for clause in UNSCOPED_COMPLETION)
    assert "For NPCs without authoritative_command_outcomes" in result
    assert "Neither speech nor a question is required" in result
    assert "Preserve resolved transfers, failures and elapsed time" in result
    assert "Stay in the protagonist's limited perspective" in result
    assert "Expressive gestures vary presentation, not command-owned fields" not in result
