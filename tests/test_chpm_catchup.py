"""Historical catch-up uses proved observers and commits only with a reviewed turn."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.engine.chpm import recovery_perception, recovery_queue
from backend.engine.chpm.recovery_contracts import RecoveryState
from backend.engine.chpm.schema import Settings
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn

TEXT = 'Miki: "Bring the sample tomorrow."\nLina privately fears failure.'


async def context(db):
    user, avatar, state, _ = await seed_vn(db)
    minute = datetime(2026, 11, 1, tzinfo=timezone.utc)
    reply = ChatMessage(
        id="missed",
        session_id=state.session_id,
        role="assistant",
        content=TEXT,
        scene_id="START",
        created_at=minute,
    )
    request = ChatMessage(
        id="request-now",
        session_id=state.session_id,
        role="user",
        content="What next?",
        created_at=minute + timedelta(hours=1),
    )
    db.add_all([reply, request])
    await db.flush()
    initial = SimpleNamespace(
        settings=Settings(mode="live", actor_ids=["LINA"]),
        recovery=RecoveryState(total_simplified_turns=1),
    )
    turn = SimpleNamespace(
        input_id=request.id,
        initial=initial,
        names={"LINA": "Lina"},
        present_names={"LINA": "Lina", "MIKI": "Miki"},
        fallback_identities={"LINA": {}},
        decisions={},
        verdict=None,
    )
    manager = SimpleNamespace(db=db, game_id=state.session_id, state=state)
    recovery_queue.stamp(manager, turn, reply)
    await db.commit()
    return manager, turn, reply


def classify(batch, **changes):
    values = {key: {"kind": "private", "observers": []} for key in batch.available}
    first = next(iter(values))
    values[first] = {"kind": "speech", "observers": ["LINA"], "speaker_id": "MIKI", **changes}
    result = recovery_perception.RecoveryProjection(fragments={}, history_fragments=values)
    recovery_perception.bind(batch, result)


async def test_catchup_is_historical_and_cannot_create_private_emotions_or_advance_without_review():
    async with TestSessionLocal() as db:
        manager, turn, reply = await context(db)
        before = deepcopy(reply.npc_recovery)
        batch = await recovery_queue.prepare(manager, turn)
        assert batch is not None
        classify(batch)
        assert batch.checked == {"LINA"} and len(batch.accepted["LINA"]) == 1
        source = batch.accepted["LINA"][0]
        assert source.reported and source.history.game_minute == 0
        assert source.message_id == reply.id and source.speaker_id == "MIKI"
        assert source.history.evidence_span.matches(TEXT, source.text)
        assert "privately" not in source.text
        turn.catchup = batch
        with pytest.raises(ValueError, match="shared successful"):
            await recovery_queue.commit(manager, turn)
        assert reply.npc_recovery == before
        turn.verdict = SimpleNamespace(matches=True)
        turn.decisions = {"LINA": object()}
        await recovery_queue.commit(manager, turn)
        await db.commit()
        assert reply.npc_recovery["actors"] == {}
        assert await recovery_queue.prepare(manager, turn) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"observers": ["ABSENT"]},
        {"kind": "private", "observers": ["LINA"]},
        {"speaker_id": "UNKNOWN"},
    ],
)
async def test_historical_attribution_rejects_unproved_audience_private_content_and_speaker(
    changes,
):
    async with TestSessionLocal() as db:
        manager, turn, reply = await context(db)
        batch = await recovery_queue.prepare(manager, turn)
        classify(batch, **changes)
        assert batch.error and not batch.checked and not batch.accepted
        assert reply.npc_recovery["actors"] == {"LINA": 0}


async def test_invalid_history_response_does_not_create_an_empty_success():
    async with TestSessionLocal() as db:
        manager, turn, _ = await context(db)
        batch = await recovery_queue.prepare(manager, turn)
        recovery_perception.bind(batch, recovery_perception.RecoveryProjection(fragments={}))
        assert batch.error and not batch.checked


async def test_source_edit_before_commit_blocks_catchup_and_checkpoint_restores_progress():
    async with TestSessionLocal() as db:
        manager, turn, reply = await context(db)
        checkpoint = await SessionCheckpointService.create_checkpoint(db, manager.game_id, "manual")
        await db.commit()
        batch = await recovery_queue.prepare(manager, turn)
        classify(batch)
        turn.catchup, turn.verdict, turn.decisions = (
            batch,
            SimpleNamespace(matches=True),
            {"LINA": object()},
        )
        await recovery_queue.commit(manager, turn)
        await db.commit()
        await SessionCheckpointService.restore_checkpoint(db, manager.game_id, checkpoint.id)
        await db.commit()
        await db.refresh(reply)
        assert reply.npc_recovery["actors"] == {"LINA": 0}
        batch = await recovery_queue.prepare(manager, turn)
        classify(batch)
        turn.catchup = batch
        reply.content = "Changed historical text."
        await db.flush()
        with pytest.raises(ValueError, match="changed"):
            await recovery_queue.commit(manager, turn)


async def test_uncertain_history_is_retained_as_unresolved_without_inventing_memory():
    async with TestSessionLocal() as db:
        manager, turn, reply = await context(db)
        batch = await recovery_queue.prepare(manager, turn)
        result = recovery_perception.RecoveryProjection(
            fragments={},
            history_fragments={
                key: {"kind": "uncertain", "observers": []} for key in batch.available
            },
        )
        recovery_perception.bind(batch, result)
        assert batch.checked and batch.accepted == {"LINA": []}
        turn.catchup, turn.verdict, turn.decisions = (
            batch,
            SimpleNamespace(matches=True),
            {"LINA": object()},
        )
        await recovery_queue.commit(manager, turn)
        audit = recovery_queue.RecoveryAudit.model_validate(reply.npc_recovery)
        assert not audit.actors and len(audit.uncertain_fragments["LINA"]) == len(batch.available)
        assert all(TEXT[span.start : span.end] for span in audit.uncertain_fragments["LINA"])


async def test_invalid_source_does_not_starve_a_later_source_or_get_marked_successful():
    async with TestSessionLocal() as db:
        manager, turn, reply = await context(db)
        later = ChatMessage(
            id="later",
            session_id=manager.game_id,
            role="assistant",
            content=TEXT,
            scene_id=reply.scene_id,
            created_at=reply.created_at + timedelta(minutes=1),
        )
        db.add(later)
        await db.flush()
        recovery_queue.stamp(manager, turn, later)
        reply.content = "Changed source."
        await db.commit()
        batch = await recovery_queue.prepare(manager, turn)
        assert batch.message.id == "later" and len(turn.catchup_unavailable) == 1
        classify(batch)
        turn.catchup, turn.verdict, turn.decisions = (
            batch,
            SimpleNamespace(matches=True),
            {"LINA": object()},
        )
        await recovery_queue.commit(manager, turn)
        assert not reply.npc_recovery["actors"]
        assert reply.npc_recovery["unavailable_actors"] == ["LINA"]
        assert reply.npc_recovery["unavailable_reason"]
        assert reply.content == "Changed source."


def test_actor_cursors_ahead_of_this_batch_are_never_rewound():
    row = SimpleNamespace(
        content="\n".join(f"Line {index}." for index in range(12)), npc_recovery=None
    )
    audit = recovery_queue.RecoveryAudit(
        content_hash="a" * 64, scene_id="S", actors={"LINA": 0, "MIKI": 9}
    )
    batch = recovery_queue._batch_view(row, audit, {"LINA": "Lina", "MIKI": "Miki"})
    assert batch.offsets == {"LINA": 0} and len(batch.available) == 4
    second = audit.model_copy(update={"actors": {"LINA": 0, "MIKI": 2}})
    batch = recovery_queue._batch_view(row, second, {"LINA": "Lina", "MIKI": "Miki"})
    observers = recovery_queue.payload(batch)["eligible_observers_by_fragment"]
    assert observers["h0"] == ["LINA"] and observers["h2"] == ["LINA", "MIKI"]


def test_history_wire_contract_has_exact_fragment_keys_without_rejecting_current_perception():
    from jsonschema import Draft202012Validator

    from backend.engine.chpm.json_contract import response_schema

    wire = response_schema(
        recovery_perception.RecoveryProjection,
        {
            "fragments": ["p0"],
            "history_fragments": ["h0"],
            "observers": ["LINA"],
            "engaged": ["LINA"],
        },
        explicit_keys=True,
    )
    current = {"p0": {"kind": "speech", "observers": ["LINA"], "engaged": ["LINA"]}}
    payload = {
        "fragments": current,
        "history_fragments": {"h0": {"kind": "private", "observers": [], "speaker_id": None}},
    }
    assert Draft202012Validator(wire).is_valid(payload)
    payload["history_fragments"] = {
        "foreign": {"kind": "private", "observers": [], "speaker_id": None}
    }
    assert not Draft202012Validator(wire).is_valid(payload)
    parsed = recovery_perception.RecoveryProjection.model_validate(
        {"fragments": current, "history_fragments": {"h0": {"kind": "invalid"}}}
    )
    assert parsed.fragments["p0"].observers == ["LINA"]


async def test_optional_history_cannot_overflow_an_otherwise_valid_current_perception(monkeypatch):
    from unittest.mock import AsyncMock

    from backend.engine.chpm import inference, perception, perception_fragments
    from backend.engine.chpm.schema import Usage

    async with TestSessionLocal() as db:
        manager, turn, _ = await context(db)
        batch = await recovery_queue.prepare(manager, turn)
        current = perception_fragments.Projection(
            fragments={
                "p0": {
                    "kind": "speech",
                    "observers": ["LINA"],
                    "engaged": ["LINA"],
                }
            }
        )
        names = {"LINA": "Lina " + "with a long public title " * 260}
        payload = {
            "fragments": {"p0": "Hello"},
            "present_observers": names,
            "recent_interlocutors": [],
        }
        ids = {"observers": ["LINA"], "engaged": ["LINA"], "fragments": ["p0"]}
        prompt, content = inference.compose(
            perception.INSTRUCTION, payload, perception_fragments.Projection, ids
        )
        settings = Settings(max_input_chars=len(prompt) + len(content) + 10)
        request = AsyncMock(return_value=current)
        monkeypatch.setattr(inference, "request", request)
        result = await perception.project(manager, settings, Usage(), "Hello", names, catchup=batch)
        assert result["LINA"].quotes == ["Hello"] and request.await_count == 1
        assert "unreviewed_history" not in request.call_args.args[4]
        assert request.call_args.args[5] is perception_fragments.Projection
        assert batch.error and not batch.checked
