"""Long-session admission is explicit, lossless and precedes CHPM model calls."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import capacity, context, runtime
from backend.engine.chpm.appraisal_contracts import GroundedProposal
from backend.engine.chpm.core import replay as replay_module
from backend.engine.chpm.core.contracts import Event
from backend.engine.chpm.core.history import events
from backend.engine.chpm.core.reducer import TransitionError, apply
from backend.engine.chpm.host_state import Mind, identifier, payload
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import KernelState, Perception, Settings, Verdict
from backend.engine.chpm.state import KEY, load
from tests.test_chpm_host_state import mind, source
from tests.test_chpm_kernel import decision
from tests.test_chpm_runtime import manager


def filled(count):
    original = mind()
    snapshot = original.snapshot
    sources = {}
    for number in range(count):
        item = source(f"m{number}", text=f"Witnessed utterance {number}")
        key = identifier(item, original.genesis)
        event = Event(
            scope=original.genesis.scope,
            event_id=key,
            sequence=number + 1,
            sim_minute=number + 1,
            payload=payload(item, original.genesis),
        )
        snapshot = apply(snapshot, event, expected_revision=snapshot.revision).snapshot
        sources[key] = item
    return Mind(genesis=original.genesis, snapshot=snapshot, sources=sources)


def test_turn_reserve_covers_all_allowed_sources_and_interpretations():
    excerpts = Perception.model_json_schema()["properties"]["quotes"]["maxItems"]
    heard = Verdict.model_json_schema()["properties"]["heard"]["maxItems"]
    interpretations = GroundedProposal.model_json_schema()["properties"]["interpretations"][
        "maxItems"
    ]
    assert 2 + excerpts + 1 + heard == capacity.SOURCE_RESERVE
    experiences = GroundedProposal.model_json_schema()["properties"]["experiences"]["maxItems"]
    assert capacity.SOURCE_RESERVE + interpretations + experiences == capacity.EVENT_RESERVE
    assert experiences == capacity.EXPERIENCE_RESERVE
    assert interpretations == capacity.BELIEF_RESERVE


def test_full_beliefs_allow_revisions_but_reject_new_beliefs_with_transition_error(monkeypatch):
    from backend.engine.chpm.core import reducer
    from tests.test_chpm_appraisal import accept, heard, proposal

    value = accept(heard(), [proposal()])
    monkeypatch.setattr(reducer, "MAX_BELIEFS", 1)
    revised = accept(value, [proposal(belief_id="b1", stance="challenge")], "revision")
    assert revised.snapshot.beliefs[0].revision == 2
    with pytest.raises(TransitionError, match="Belief capacity"):
        accept(value, [proposal(statement="Different expectation")])


def test_full_experience_dimensions_allow_reassessment_only(monkeypatch):
    from backend.engine.chpm.core import experience as core_experience
    from tests.test_chpm_appraisal import heard
    from tests.test_chpm_experience import accept, proposed

    value, _ = accept(heard(text="You must obey"), [proposed()])
    monkeypatch.setattr(core_experience, "MAX_EXPERIENCES", 1)
    value = heard(value, "m2", "You must obey again")
    reference = [{"source_id": "e2", "quote": "You must obey again"}]
    revised, _ = accept(value, [proposed(level="high", citations=reference)], "m2")
    assert revised.snapshot.experiences[0].level == "high"
    with pytest.raises(TransitionError, match="Experience capacity"):
        accept(value, [proposed(dimension="anger", citations=reference)], "m2")


def test_boundary_admits_a_whole_turn_then_requires_explicit_pause(monkeypatch):
    monkeypatch.setattr(capacity, "MAX_EVENTS", 512)
    value = filled(512 - capacity.EVENT_RESERVE)
    state = KernelState(settings=Settings(mode="live", actor_ids=["npc"]), minds={"npc": value})
    assert capacity.inspect(value)["status"] == "warning"
    capacity.ensure_turn(state, ["npc"])
    over = filled(512 - capacity.EVENT_RESERVE + 1)
    state.minds["npc"] = over
    before = state.model_dump()
    with pytest.raises(ChpmError, match="explicitly choose Standard"):
        capacity.ensure_turn(state, ["npc"])
    assert state.model_dump() == before
    state.settings.mode = "off"
    capacity.ensure_turn(state, ["npc"])
    assert state.minds["npc"] == over


async def test_full_journal_stops_before_any_chpm_preparation_and_preserves_saved_state(
    monkeypatch,
):
    monkeypatch.setattr(capacity, "MAX_EVENTS", 512)
    host, actor = manager("live")
    value = filled(512)
    saved = load(host.state)
    saved.minds["npc"] = value
    host.state.entity_states[KEY] = saved.model_dump()
    before = load(host.state)
    prepare = AsyncMock(side_effect=AssertionError("No inference or pending observations"))
    monkeypatch.setattr(runtime, "_prepare", prepare)
    monkeypatch.setattr(capacity.host_sources, "reconcile", AsyncMock(return_value=value))
    with pytest.raises(ChpmError, match="psychological history"):
        await runtime.prepare(host, "Hello", [actor])
    prepare.assert_not_called()
    assert load(host.state) == before
    assert runtime.current(host).usage.calls == 0
    assert capacity.inspect(value)["status"] == "pause_required"


async def test_capacity_admission_allows_normal_reconciliation_to_free_invalid_sources(monkeypatch):
    monkeypatch.setattr(capacity, "MAX_EVENTS", 512)
    value = filled(512)
    state = KernelState(settings=Settings(mode="live", actor_ids=["npc"]), minds={"npc": value})
    original = state.model_dump()
    monkeypatch.setattr(capacity.host_sources, "reconcile", AsyncMock(return_value=mind()))
    await capacity.admit(SimpleNamespace(), state, ["npc"])
    assert state.model_dump() == original


def test_legacy_budget_loads_but_three_actor_live_turn_needs_repair_reserve():
    settings = Settings(mode="live", actor_ids=["a", "b", "c"], max_calls_per_turn=6)
    state = KernelState(settings=settings)
    assert KernelState.model_validate_json(state.model_dump_json()).settings.max_calls_per_turn == 6
    with pytest.raises(ChpmError, match="at least 7"):
        capacity.ensure_turn(state, ["a", "b", "c"])
    capacity.ensure_turn(state, ["a", "b"])
    state.settings.max_calls_per_turn = Settings().max_calls_per_turn
    capacity.ensure_turn(state, ["a", "b", "c"])
    assert capacity.required_calls(state.settings) == 7
    state.settings.mode = "shadow"
    assert capacity.required_calls(state.settings) == 4


def test_replay_reuses_verified_prefixes_and_still_rejects_tampered_projection(monkeypatch):
    value = filled(480)
    replay_module._checkpoint.cache_clear()
    wrapped = []
    original_apply = replay_module.apply

    def counted(*args, **kwargs):
        wrapped.append(1)
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(replay_module, "apply", counted)
    raw = value.snapshot.model_dump()
    assert replay_module.restore(raw, expected_genesis=value.genesis) == value.snapshot
    assert len(wrapped) == 480
    wrapped.clear()
    assert replay_module.restore(raw, expected_genesis=value.genesis) == value.snapshot
    assert wrapped == []
    event = Event(
        scope=value.genesis.scope,
        event_id="next",
        sequence=481,
        sim_minute=481,
        payload={"kind": "advance"},
    )
    updated = replay_module.replay(value.genesis, (*events(value.snapshot), event))
    assert len(wrapped) == 1 and updated.cursor == 481
    raw["sim_minute"] = 999
    with pytest.raises(TransitionError, match="projection disagrees"):
        replay_module.restore(raw, expected_genesis=value.genesis)


async def test_host_assigns_revision_order_with_tied_naive_timestamps_and_retains_retry_order():
    host, _ = manager("live")
    created = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    old = decision(
        message_id="zzzz", sequence=int(created.timestamp() * 1_000_000), turn_revision=7
    )
    state = KernelState(
        settings=Settings(mode="live", actor_ids=["npc"]), revision=7, actors={"npc": old}
    )
    host.state.entity_states[KEY] = state.model_dump()
    row = SimpleNamespace(
        id="aaaa",
        session_id="session",
        role="user",
        content="Hello",
        created_at=created.replace(tzinfo=None),
        revision_id="r",
        scene_id="room",
    )
    host._vn_player_message_id = row.id
    host.db = SimpleNamespace(get=AsyncMock(return_value=row))
    host.state.in_game_time = 5
    observed = await context.observation(host, "Hello")
    assert observed.sequence == old.observation.sequence
    assert observed.turn_revision == 8
    from backend.engine.chpm.kernel import existing

    assert existing(old, observed, "new") is None
    state.actors["npc"] = old.model_copy(update={"observation": observed})
    state.revision = 8
    host.state.entity_states[KEY] = state.model_dump()
    assert (await context.observation(host, "Hello")).turn_revision == 8


async def test_three_npcs_have_room_for_one_repair_and_review_using_narrator_role(monkeypatch):
    from backend.engine.chpm import inference, rendering
    from backend.engine.chpm.schema import SpokenEvidence, Usage

    host, _ = manager("live")
    settings = Settings(mode="live", actor_ids=["a", "b", "c"], model_role="small")
    text = "A speaks. B speaks. C speaks."
    turn = runtime.Turn(
        KernelState(settings=settings),
        "input",
        usage=Usage(calls=4),
        decisions={
            actor: decision().model_copy(update={"actor_id": actor}) for actor in settings.actor_ids
        },
    )
    host._chpm_turn = turn
    reviews = iter(
        [
            Verdict(matches=False, issues=["Repair needed"]),
            Verdict(
                matches=True,
                evidence=[
                    SpokenEvidence(actor_id=actor, quote=f"{actor.upper()} speaks.")
                    for actor in settings.actor_ids
                ],
            ),
        ]
    )

    async def review(_host, prefs, usage, *_args, **_kwargs):
        inference.reserve(prefs, usage, 100)
        return next(reviews)

    model = SimpleNamespace(
        enable_thinking=True,
        max_tokens=4096,
        model="mock",
        request_timeout=10,
        aexecute_simple_task=AsyncMock(return_value=text),
    )
    roles = []

    def model_for(_host, role, _router):
        roles.append(role)
        return model

    monkeypatch.setattr(inference, "request", review)
    monkeypatch.setattr(inference, "model_for", model_for)
    assert (
        await rendering.validate(host, text, completed=True, resolution="", system_prompt="")
        == text
    )
    assert turn.usage.calls == 7 and turn.usage.repairs == 1
    assert roles == ["complex"]
