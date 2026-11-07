"""Canonical bodily facts must reach citable host evidence, not only side context."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import appraisal_context, host_adapter, host_observations
from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.host_observation_contracts import HostFacts
from backend.engine.chpm.host_state import Mind, fingerprint, identifier, record
from backend.engine.chpm.schema import KernelState, Perception
from backend.engine.physical_conditions.ledger import apply
from backend.engine.physical_conditions.schema import KEY, MAX_ACTIVE, Condition, Ledger, Source
from tests.test_chpm_host_state import mind, source
from tests.test_chpm_kernel import observation
from tests.test_physical_conditions import record as proposal


def state_with_conditions():
    rows = [
        proposal(target_id=actor, part=part, detail=detail)
        for actor, part, detail in [
            ("npc", "neck", "OWN_PRIVATE_WOUND"),
            ("coat", "cuff", "OWN_COAT_DIRT"),
            ("other", "neck", "FOREIGN_BODY_SECRET"),
            ("hidden", "fabric", "FOREIGN_ITEM_SECRET"),
        ]
    ]
    states, _, errors = apply(
        {},
        rows,
        targets={"npc", "coat", "other", "hidden"},
        narration="Rin has an open neck wound.",
        message_id="original",
        session_id="session",
        minute=0,
    )
    assert not errors
    return SimpleNamespace(current_scene_id="room", entity_states=states)


def actor():
    return SimpleNamespace(id="npc", inventory=[{"id": "coat", "name": "Coat"}], metadata_json={})


def capture(state):
    return host_observations.capture(state, actor(), {"npc": "Rin", "other": "Other"})


def change(state, identifier, operation, message):
    state.entity_states, accepted, errors = apply(
        state.entity_states,
        [{"operation": operation, "condition_id": identifier, "evidence": message}],
        targets={"npc", "coat"},
        narration=message,
        message_id=message,
        session_id="session",
        minute=1,
    )
    assert accepted == [identifier] and not errors


def test_current_body_and_owned_item_facts_reach_self_inspection_without_foreign_secrets():
    state = state_with_conditions()
    facts = capture(state)
    original = deepcopy(state.entity_states)
    text = host_observations.frame(facts)
    assert "OWN_PRIVATE_WOUND" in text and "OWN_COAT_DIRT" in text
    assert "FOREIGN_BODY_SECRET" not in text and "FOREIGN_ITEM_SECRET" not in text
    frame = source("m1", text, "host_frame").model_copy(update={"facts": facts})
    value = record(mind(), frame, minute=0)
    tools = Tools(value, observation(message_id="m1"), {})
    result = tools.execute(Lookup(tool="inspect_self"))
    assert result["kind"] == "witnessed" and "OWN_PRIVATE_WOUND" in result["text"]
    assert result["source_id"] in appraisal_context.build(value, pinned=tools.pins).sources
    assert state.entity_states == original


def test_treatment_and_explicit_resolution_are_current_changes_not_disappearing_facts():
    state = state_with_conditions()
    before = capture(state)
    identifier = next(
        row.id
        for row in Ledger.model_validate(state.entity_states[KEY]).conditions.values()
        if row.target_id == "npc"
    )
    change(state, identifier, "treat", "Rin disinfects the neck wound.")
    treated = capture(state)
    assert '"treated"' in host_observations.frame(treated)
    change(state, identifier, "heal", "Rin's neck wound is completely healed.")
    after = capture(state)
    delta = json.loads(host_observations.difference(treated, after))
    assert delta["own_physical_conditions_changed"][0]["status"] == "resolved"
    assert delta["own_physical_conditions_changed"][0]["id"] == identifier
    assert delta["cause"] == "unknown"
    assert '"resolved"' in host_observations.frame(after)
    assert host_observations.difference(after, after) is None
    assert '"active"' in host_observations.frame(before)


def test_missing_or_corrupt_ledger_does_not_establish_healing():
    state = state_with_conditions()
    before = capture(state)
    state.entity_states = {KEY: {"version": 999}}
    unknown = capture(state)
    assert unknown.physical_conditions is None
    assert host_observations.difference(before, unknown) is None
    state.entity_states = {KEY: Ledger(revision=1).model_dump()}
    missing = json.loads(host_observations.difference(before, capture(state)))
    assert missing["own_physical_conditions_unavailable"]
    assert "resolved" not in json.dumps(missing)


def test_legacy_frame_payload_and_source_hash_do_not_change_on_roundtrip():
    raw = {"scene_id": "room", "visible_actor_ids": [], "owned_items": None, "worn_item_ids": None}
    facts = HostFacts.model_validate(raw)
    assert facts.model_dump(mode="json") == raw
    frame = source(kind="host_frame", text="Legacy frame").model_copy(update={"facts": facts})
    body = frame.model_dump()
    body.pop("graph")
    body["facts"] = raw
    value = mind()
    assert identifier(frame, value.genesis) == fingerprint(
        {"scope": value.genesis.scope.model_dump(), "source": body}
    )
    saved = record(value, frame, minute=0)
    assert Mind.model_validate_json(saved.model_dump_json()) == saved


def test_maximum_physical_frame_is_bounded_and_preserves_the_full_typed_snapshot():
    state = state_with_conditions()
    origin = Source(kind="manual", quote="Manual condition.")
    rows = {
        f"condition-{i}": Condition(
            id=f"condition-{i}",
            target_id="npc",
            kind="injury",
            part=f"area {i}",
            detail="An injury. " * 25,
            origin=origin,
            latest=origin,
            updated_revision=i,
        )
        for i in range(MAX_ACTIVE)
    }
    state.entity_states = {KEY: Ledger(conditions=rows).model_dump()}
    facts = capture(state)
    text = host_observations.frame(facts)
    assert len(text) <= 2000
    assert json.loads(text)["omitted"]["physical_conditions"] > 0
    assert len(facts.physical_conditions) == MAX_ACTIVE
    assert HostFacts.model_validate_json(facts.model_dump_json()) == facts


@pytest.mark.asyncio
async def test_host_delta_is_citable_evidence_for_resolution_and_survives_reload(monkeypatch):
    monkeypatch.setattr(
        host_adapter.host_sources, "reconcile", AsyncMock(side_effect=lambda manager, value: value)
    )
    state = state_with_conditions()
    manager = SimpleNamespace(game_id="session", state=state)
    turn = SimpleNamespace(
        initial=KernelState(minds={"npc": mind()}),
        minds={},
        present_names={"npc": "Rin"},
        perceptions={"npc": Perception(actor_id="npc", quotes=[])},
    )
    observed = observation(message_id="before")
    first = await host_adapter.prepare(manager, turn, actor(), observed)
    identifier = next(
        row.id
        for row in Ledger.model_validate(state.entity_states[KEY]).conditions.values()
        if row.target_id == "npc"
    )
    change(state, identifier, "heal", "The wound has completely healed.")
    turn.initial.minds["npc"] = first
    next_observation = observation(message_id="after")
    second = await host_adapter.prepare(manager, turn, actor(), next_observation)
    deltas = [entry for entry in second.sources.values() if entry.kind == "world_event"]
    assert len(deltas) == 1 and '"resolved"' in deltas[0].text
    tools = Tools(second, next_observation, {})
    result = tools.execute(Lookup(tool="inspect_self"))
    assert '"resolved"' in result["text"]
    assert result["source_id"] in appraisal_context.build(second, pinned=tools.pins).sources
    assert Mind.model_validate_json(second.model_dump_json()) == second
    assert second.genesis == first.genesis


def test_resolved_public_condition_remains_explicit_in_narration_but_private_ones_do_not_leak():
    from backend.engine.physical_conditions.presentation import narration_block

    state = state_with_conditions()
    ledger = Ledger.model_validate(state.entity_states[KEY])
    own = next(row for row in ledger.conditions.values() if row.target_id == "npc")
    ledger.conditions[own.id].visibility = "public"
    state.entity_states = {KEY: ledger.model_dump()}
    change(state, own.id, "heal", "The neck wound is fully healed.")
    text = narration_block(state, {"npc": {"resolved_inventory": []}}, detailed=True)
    assert own.id in text and '"resolved"' in text
    assert '"active": []' in text
    assert "OWN_PRIVATE_WOUND" not in text  # The old open-wound detail is no longer current.
    assert "FOREIGN_BODY_SECRET" not in text and "OWN_COAT_DIRT" not in text


def test_compact_live_context_uses_one_citable_body_channel_and_keeps_unknown_warnings():
    state = state_with_conditions()
    facts = capture(state)
    frame = source("m1", host_observations.frame(facts), "host_frame").model_copy(
        update={"facts": facts}
    )
    value = record(mind(), frame, minute=0)
    supplied = {"own_physical_conditions": {"status": "available", "active": ["duplicate"]}}
    host_adapter.add_context(supplied, value)
    assert "own_physical_conditions" not in supplied
    assert "OWN_PRIVATE_WOUND" in json.dumps(supplied)
    unknown = HostFacts(scene_id="room")
    unknown_source = source("m2", host_observations.frame(unknown), "host_frame").model_copy(
        update={"facts": unknown}
    )
    value = record(value, unknown_source, minute=1)
    supplied = {"own_physical_conditions": {"status": "unavailable"}}
    host_adapter.add_context(supplied, value)
    assert supplied["own_physical_conditions"]["status"] == "unavailable"


def test_leaving_an_item_behind_does_not_mean_its_condition_has_been_cleaned():
    state = state_with_conditions()
    before = capture(state)
    state.entity_states = {**state.entity_states, "npc": {"inventory": []}}
    after = capture(state)
    delta = json.loads(host_observations.difference(before, after))
    assert delta["own_items_lost"] == [{"id": "coat", "name": "Coat"}]
    assert delta["own_physical_conditions_unavailable"]
    assert "resolved" not in json.dumps(delta)
    assert "OWN_COAT_DIRT" not in host_observations.frame(after)


def test_unreviewed_fallback_does_not_publish_an_observers_private_body_context():
    from backend.engine.chpm import continuation

    state = state_with_conditions()
    who = actor()
    who.name = "Rin"
    manager = SimpleNamespace(game_id="session", state=state)
    fallback = continuation.identities(manager, KernelState(), [who])
    assert "OWN_PRIVATE_WOUND" not in json.dumps(fallback)
    assert "OWN_COAT_DIRT" not in json.dumps(fallback)
    assert fallback["npc"]["current_host_state"]["owned_items"] == ({"id": "coat", "name": "Coat"},)
