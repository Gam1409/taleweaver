"""Bounded retention, optional extraction isolation and observer-scoped projections."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.engine.chpm.context import actor_context
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.ledger import apply, read, remap
from backend.engine.physical_conditions.presentation import context, narration_block
from backend.engine.physical_conditions.runtime import finish, stage
from backend.engine.physical_conditions.schema import (
    KEY,
    MAX_ACTIVE,
    MAX_EVENTS,
    MAX_RESOLVED,
    Condition,
    Ledger,
    Source,
)
from tests.test_physical_conditions import record, run


def saved(count=1, status="active"):
    source = Source(
        kind="narration", message_id="original", content_hash="a" * 64, quote="A wound."
    )
    return {
        KEY: Ledger(
            conditions={
                str(i): Condition(
                    id=str(i),
                    target_id="RIN",
                    kind="injury",
                    part=f"part{i}",
                    detail="A wound.",
                    status=status,
                    origin=source,
                    latest=source,
                    updated_revision=i,
                )
                for i in range(count)
            }
        ).model_dump()
    }


def test_active_capacity_refuses_only_new_facts_but_still_allows_resolution():
    states = saved(MAX_ACTIVE)
    changed, accepted, errors = run(states, [record()])
    assert errors and not accepted and len(read(changed).conditions) == MAX_ACTIVE
    healed, accepted, errors = run(
        changed,
        [{"operation": "heal", "condition_id": "0", "evidence": "The wound healed."}],
        reply="R2",
    )
    assert not errors and accepted == ["0"]
    added, accepted, errors = run(healed, [record()], reply="R3")
    assert not errors and accepted and len(read(added).conditions) == MAX_ACTIVE + 1


def test_only_resolved_records_are_pruned_and_retention_is_explicit():
    states = saved(MAX_RESOLVED + 1, status="resolved")
    changed, _, _ = run(states, [record()])
    ledger = read(changed)
    assert ledger.archived_resolved == 1 and len(ledger.conditions) == MAX_RESOLVED + 1
    assert "0" not in ledger.conditions
    # Repeated explicit description changes exercise the bounded recent audit, not fact eviction.
    identifier = next(row.id for row in ledger.conditions.values() if row.status == "active")
    for i in range(MAX_EVENTS + 2):
        changed, _, errors = run(
            changed,
            [
                {
                    "operation": "change",
                    "condition_id": identifier,
                    "detail": f"Wound check {i}.",
                    "evidence": "The wound is still there.",
                }
            ],
            reply=f"update{i}",
        )
        assert not errors
    ledger = read(changed)
    assert len(ledger.events) == MAX_EVENTS and ledger.archived_events == 3
    assert ledger.conditions[identifier].status == "active"


def test_copies_remap_all_sources_and_mark_missing_anchors_without_dropping_facts():
    original = saved()
    copy = remap(original, {"original": "new"})
    assert read(copy).conditions["0"].origin.message_id == "new"
    assert read(original).conditions["0"].origin.message_id == "original"
    unavailable = read(remap(original, {})).conditions["0"]
    assert unavailable.origin.kind == "unavailable" and unavailable.origin.message_id is None
    assert unavailable.detail == "A wound." and unavailable.origin.quote == "A wound."


def test_optional_bad_condition_does_not_make_valid_item_extraction_unparseable():
    extraction = ItemExtraction.model_validate(
        {"actions": [], "condition_updates": [{"operation": "invalid"}, record()]}
    )
    _, accepted, errors = run({}, extraction.condition_updates)
    assert len(accepted) == 1 and len(errors) == 1
    assert ItemExtraction.model_validate({"condition_updates": "broken"}).condition_updates == [
        "broken"
    ]
    schema = ItemExtraction.model_json_schema()
    assert schema["properties"]["condition_updates"]["maxItems"] == 12
    assert "ConditionProposal" in schema["$defs"]
    assert not ItemExtraction().condition_updates


@pytest.mark.asyncio
async def test_narrator_sees_public_facts_and_each_npc_sees_only_own_private_state():
    conditions = [
        record(target_id=who, detail=detail, visibility=visibility)
        for who, detail, visibility in [
            ("RIN", "RIN_PRIVATE", "private"),
            ("MIKI", "MIKI_PUBLIC", "public"),
            ("__player__", "PLAYER_PRIVATE", "private"),
            ("SECRET_COAT", "SECRET_ITEM", "public"),
        ]
    ]
    states, _, errors = apply(
        {},
        conditions,
        targets={"RIN", "MIKI", "__player__", "SECRET_COAT"},
        narration="Rin has an open neck wound.",
        message_id="msg",
        session_id="S",
        minute=0,
    )
    assert not errors
    state = SimpleNamespace(entity_states=states)
    actors = {who: {"resolved_inventory": []} for who in ("RIN", "MIKI", "__player__")}
    text = narration_block(state, actors, detailed=True)
    assert "MIKI_PUBLIC" in text and "PLAYER_PRIVATE" in text
    assert "RIN_PRIVATE" not in text and "SECRET_ITEM" not in text
    actor = SimpleNamespace(id="RIN", name="Rin")
    own = await actor_context(SimpleNamespace(state=state), actor, None)
    assert "RIN_PRIVATE" in json.dumps(own)
    assert "MIKI_PUBLIC" not in json.dumps(own) and "PLAYER_PRIVATE" not in json.dumps(own)
    assert context(state, {"ABSENT"})["active"] == []


def test_pending_check_refuses_a_concurrent_ledger_replacement():
    manager = SimpleNamespace(
        state=SimpleNamespace(entity_states=saved(), session_id="S", in_game_time=0)
    )
    pending = stage(manager, [], set(), error="Not completed yet.")
    manager.state.entity_states = saved(2)
    pending.complete([record()], {"RIN"})
    before = deepcopy(manager.state.entity_states)
    assert (
        "changed during"
        in finish(manager, SimpleNamespace(id="reply", content="Rin has an open neck wound."))[0]
    )
    assert manager.state.entity_states == before


def test_nonexistent_source_anchor_and_excess_proposals_are_rejected():
    with pytest.raises(ValidationError):
        Source(kind="narration", quote="An invented anchor.")
    states, accepted, errors = run({}, [record()] * 13)
    assert not accepted and errors and not read(states).conditions


def test_player_own_private_equipment_is_known_but_foreign_private_items_are_not():
    from backend.engine.physical_conditions.presentation import targets_from_actors

    proposals = [
        record(target_id=identifier, detail=identifier)
        for identifier in ("PLAYER_COAT", "FOREIGN_COAT")
    ]
    states, _, errors = apply(
        {},
        proposals,
        targets={"PLAYER_COAT", "FOREIGN_COAT"},
        narration="Rin has an open neck wound.",
        message_id="msg",
        session_id="S",
        minute=0,
    )
    assert not errors
    actors = {
        "__player__": {"equipment": {"Chest": {"id": "PLAYER_COAT"}}, "resolved_inventory": []}
    }
    assert "PLAYER_COAT" in targets_from_actors(actors)
    prompt = narration_block(SimpleNamespace(entity_states=states), actors, detailed=True)
    assert "PLAYER_COAT" in prompt and "FOREIGN_COAT" not in prompt


@pytest.mark.asyncio
async def test_an_incomplete_reply_discards_a_previous_uncommitted_proposal():
    from backend.engine.narrated_items.runtime import reconcile_items

    manager = SimpleNamespace(
        state=SimpleNamespace(entity_states=saved(), session_id="S", in_game_time=0)
    )
    stage(manager, [record()], {"RIN"})
    before = deepcopy(manager.state.entity_states)
    assert (
        await reconcile_items(
            manager, "Rin has an open neck wound.", completed=False, resolution=""
        )
        == []
    )
    assert (
        finish(manager, SimpleNamespace(id="partial", content="Rin has an open neck wound.")) == []
    )
    assert manager.state.entity_states == before
