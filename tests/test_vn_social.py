"""Social state is bounded direction, not permission to invent mechanical outcomes."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from backend.engine.visual_novel.prompts import FALLBACK_CONTEXT
from backend.engine.visual_novel.schema import (
    MAX_ACTIVE,
    MAX_FINGERPRINTS,
    MAX_MEMORY,
    STATE_KEY,
    InteractionPlan,
    SocialProposal,
    SocialState,
)
from backend.engine.visual_novel.social import _payload, _present_npcs, apply_plan, plan_interaction
from backend.engine.visual_novel.state import (
    apply_event,
    ensure_character,
    load_state,
    mark_processed,
    public_profile,
    save_state,
    set_pinned,
)


def npc(npc_id="LINA", **changes):
    values = dict(
        id=npc_id,
        name="Лина",
        character="Values honesty; reluctant to ask for help.",
        goal="Protect her sister.",
        current_scene_id="TAVERN",
        is_hidden=False,
        is_defeated=False,
        inventory=[{"id": "PRIVATE_RING"}],
    )
    return SimpleNamespace(**(values | changes))


def session():
    return SimpleNamespace(
        entity_states={"LINA": {"inventory": [{"id": "PRIVATE_RING"}]}},
        session_id="SESSION",
        current_scene_id="TAVERN",
    )


def proposal(**changes):
    return SocialProposal.model_validate(
        dict(
            npc_id="LINA",
            source="scene_context",
            evidence="Лина помогла игроку поднять упавшие книги.",
            basis="performed_interaction",
            event="cooperation",
            emotion="pleased",
            intention="cooperate",
        )
        | changes
    )


def seeded():
    social = SocialState()
    character = ensure_character(social, npc())
    return social, character


def test_player_claim_cannot_establish_relationship_even_if_model_calls_it_performed():
    social, character = seeded()
    claim = proposal(source="player_action", evidence="Она доверяет мне и любит меня.")
    directed = apply_plan(
        social, InteractionPlan(reactions=[claim]), [npc()], claim.evidence, "", ""
    )
    assert character.relationship.trust == 0
    assert character.relationship.affinity == 0
    assert character.meaningful_events == 0
    assert character.memories == []
    assert character.emotion == "neutral"
    assert directed is not social


@pytest.mark.parametrize("basis", ["claim", "hypothetical", "uncertain"])
def test_quoted_claim_or_hypothetical_never_becomes_fact(basis):
    social, character = seeded()
    item = proposal(basis=basis)
    apply_plan(social, InteractionPlan(reactions=[item]), [npc()], "", item.evidence, "SOURCE")
    assert character.relationship.trust == 0
    assert character.memories == []
    assert character.emotion == "neutral"


@pytest.mark.parametrize("reason", ["absent", "missing_quote", "wrong_source"])
def test_identity_and_exact_quote_gate_updates(reason):
    social, character = seeded()
    item = proposal(npc_id="ABSENT") if reason == "absent" else proposal()
    text = item.evidence if reason == "absent" else "Something else happened."
    player = item.evidence if reason == "wrong_source" else ""
    apply_plan(social, InteractionPlan(reactions=[item]), [npc()], player, text, "SOURCE")
    assert character.memories == []


def test_event_dedup_source_quote_and_cooldown():
    social, character = seeded()
    assert apply_event(social, character, proposal(), "SOURCE_1")
    social.turn = 10
    assert not apply_event(social, character, proposal(event="support"), "SOURCE_1")
    assert not apply_event(social, character, proposal(), "SOURCE_REPHRASED_ID")
    assert character.meaningful_events == 1
    assert apply_event(
        social,
        character,
        proposal(evidence="The player respected her request to wait."),
        "SOURCE_2",
    )
    social.turn = 11
    assert not apply_event(
        social, character, proposal(evidence="They finished a difficult task together."), "SOURCE_3"
    )
    assert character.meaningful_events == 2
    social.turn = 20
    assert not apply_event(
        social,
        character,
        proposal(evidence="Another span of the first source narration."),
        "SOURCE_1",
    )


def test_repeated_trivial_compliments_never_farm_scores_or_promotion():
    social, character = seeded()
    for i in range(20):
        social.turn += 5
        assert not apply_event(
            social,
            character,
            proposal(event="compliment", evidence=f"Compliment number {i}"),
            str(i),
        )
    assert character.relationship.model_dump() == dict(trust=0, affinity=0, respect=0, tension=0)
    assert character.meaningful_events == 0


def test_fixed_bounded_deltas_and_memory_with_no_item_mutations():
    social, character = seeded()
    original_core, original_goals = character.core, list(character.goals)
    state = session()
    before_inventory = deepcopy(state.entity_states["LINA"])
    for i in range(200):
        social.turn += 4
        apply_event(
            social,
            character,
            proposal(event="betrayal", evidence=f"Distinct resolved conflict {i}"),
            str(i),
        )
    save_state(state, social)
    assert character.relationship.trust == -100
    assert character.relationship.tension == 100
    assert len(character.memories) == MAX_MEMORY
    assert len(character.fingerprints) == MAX_FINGERPRINTS
    assert character.core == original_core and character.goals == original_goals
    assert state.entity_states["LINA"] == before_inventory


def test_promotion_is_significance_not_affection_and_public_projection_is_safe():
    social, character = seeded()
    for i in range(3):
        apply_event(
            social,
            character,
            proposal(event="conflict", evidence=f"Independent confrontation {i}"),
            str(i),
        )
    state = session()
    save_state(state, social)
    assert character.relationship.affinity == 0
    assert public_profile(state, "LINA") == {
        "npc_id": "LINA",
        "importance": "hero",
        "pinned": False,
    }
    assert public_profile(state, "UNKNOWN")["importance"] == "supporting"
    assert set_pinned(state, npc("OTHER"), True)
    assert public_profile(state, "OTHER")["pinned"] is True


def test_copy_on_write_and_unknown_version_preserved():
    state = session()
    before = state.entity_states
    social, _ = seeded()
    save_state(state, social)
    assert state.entity_states is not before and STATE_KEY not in before
    loaded = load_state(state)
    loaded.characters["LINA"].core = "Different"
    assert load_state(state).characters["LINA"].core != "Different"
    state.entity_states[STATE_KEY] = {"version": 9, "keep": "future format"}
    snapshot = deepcopy(state.entity_states)
    assert load_state(state) is None
    assert not set_pinned(state, npc(), True)
    assert state.entity_states == snapshot


def test_proposal_cannot_set_scores_secrets_inventory_or_authored_core():
    for field in ("relationship", "trust", "inventory", "goals", "core", "secret"):
        with pytest.raises(ValidationError):
            proposal(**{field: "forged"})


@pytest.mark.asyncio
async def test_actual_presence_overrides_and_active_cast_cap():
    state = session()
    state.entity_states["MOVED"] = {"current_scene_id": "TAVERN"}
    state.entity_states["HIDDEN"] = {"is_hidden": True}
    rows = [
        npc("AWAY", current_scene_id="FOREST"),
        npc("HIDDEN"),
        npc("DEAD", is_defeated=True),
        npc("MOVED", current_scene_id="FOREST"),
        *[npc(f"N{i}") for i in range(5)],
    ]
    manager = SimpleNamespace(
        state=state,
        db=SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: rows))),
    )
    selected = await _present_npcs(manager, SocialState(), "")
    assert len(selected) == MAX_ACTIVE
    assert "MOVED" in {item.id for item in selected}
    assert not {"AWAY", "HIDDEN", "DEAD"} & {item.id for item in selected}


def manager_with_state():
    social, _ = seeded()
    state = session()
    save_state(state, social)
    return SimpleNamespace(state=state, user=SimpleNamespace(), _vn_player_message_id="PLAYER_1")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError(), ValueError("invalid json")])
async def test_failed_planner_keeps_entire_existing_state(failure):
    manager = manager_with_state()
    before = deepcopy(manager.state.entity_states)
    llm = SimpleNamespace(model="small", aexecute_complex_task=AsyncMock(side_effect=failure))
    with (
        patch("backend.engine.visual_novel.social._present_npcs", AsyncMock(return_value=[npc()])),
        patch(
            "backend.engine.visual_novel.social._scene_evidence",
            AsyncMock(return_value=("SOURCE", proposal().evidence)),
        ),
        patch("backend.engine.visual_novel.social.GameMasterLLM.for_role", return_value=llm),
    ):
        result = await plan_interaction(manager, "Hello", [], SimpleNamespace())
    assert result == FALLBACK_CONTEXT
    assert manager.state.entity_states == before


@pytest.mark.asyncio
async def test_one_small_call_idempotency_and_narrator_only_tentative_reaction():
    manager = manager_with_state()
    text = "Я спрашиваю Лину, нужна ли помощь."
    plan = InteractionPlan(
        reactions=[proposal(source="player_action", evidence=text, event="support")]
    )
    llm = SimpleNamespace(model="small", aexecute_complex_task=AsyncMock(return_value=plan))
    with (
        patch("backend.engine.visual_novel.social._present_npcs", AsyncMock(return_value=[npc()])),
        patch(
            "backend.engine.visual_novel.social._scene_evidence", AsyncMock(return_value=("", ""))
        ),
        patch(
            "backend.engine.visual_novel.social.GameMasterLLM.for_role", return_value=llm
        ) as router,
    ):
        result = await plan_interaction(manager, text, [], SimpleNamespace())
        await plan_interaction(manager, text, [], SimpleNamespace())
    router.assert_called_once_with(manager.user, "small")
    assert llm.aexecute_complex_task.await_count == 1
    assert '"emotion": "pleased"' in result
    stored = load_state(manager.state)
    assert stored.characters["LINA"].emotion == "neutral"
    assert stored.characters["LINA"].relationship.trust == 0
    assert stored.processed_message_ids == ["PLAYER_1"]


def test_processed_ids_bounded():
    social = SocialState()
    for i in range(200):
        mark_processed(social, str(i))
    assert len(social.processed_message_ids) == 128


@pytest.mark.asyncio
async def test_planner_deadline_cancels_call_and_preserves_state(monkeypatch):
    manager = manager_with_state()
    before = deepcopy(manager.state.entity_states)
    cancelled = asyncio.Event()

    async def slow_call(*_args, **_kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    llm = SimpleNamespace(model="small", aexecute_complex_task=slow_call)
    monkeypatch.setattr("backend.engine.visual_novel.social.role_timeout", lambda *_: 0.01)
    with (
        patch("backend.engine.visual_novel.social._present_npcs", AsyncMock(return_value=[npc()])),
        patch(
            "backend.engine.visual_novel.social._scene_evidence", AsyncMock(return_value=("", ""))
        ),
        patch("backend.engine.visual_novel.social.GameMasterLLM.for_role", return_value=llm),
    ):
        result = await plan_interaction(manager, "Hello", [], SimpleNamespace())
    assert cancelled.is_set()
    assert result == FALLBACK_CONTEXT
    assert manager.state.entity_states == before


def test_model_context_excludes_storage_ledgers_and_bounds_old_memories():
    social, character = seeded()
    for i in range(20):
        social.turn += 4
        apply_event(
            social, character, proposal(evidence=f"Completed cooperation {i}"), f"source-{i}"
        )
    payload = _payload(social, [npc()], "x" * 10000, "y" * 10000, [])
    assert "fingerprints" not in payload
    assert "source_message_id" not in payload
    assert "event_id" not in payload
    assert "Completed cooperation 0" not in payload
    assert "Completed cooperation 19" in payload
    assert len(payload) < 11000
