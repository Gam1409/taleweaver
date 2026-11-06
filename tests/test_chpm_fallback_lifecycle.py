"""Unreviewed intervals survive saves and stay tied to the correct story sources."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import continuation, lifecycle, runtime
from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.recovery_contracts import RecoveryState, SimplifiedReply
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load, retract, save
from backend.engine.turn_replay.snapshot import capture, restore
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import chpm_world, portrait_world
from tests.test_chpm_fallback import continuing
from tests.test_chpm_host_state import mind, record, source

__all__ = ["chpm_world", "portrait_world"]


def gap():
    return RecoveryState(
        pending_gap_turns=1,
        total_simplified_turns=1,
        last_gap_revision=2,
        gap_cursors={"npc": 1},
        recent=[
            SimplifiedReply(
                input_id="input",
                reply_id="reply",
                reply_revision="v1",
                reply_hash="hash",
                reason="analysis_failed",
                actor_ids=["npc"],
            )
        ],
    )


def test_session_fork_rebinds_gap_sources_and_keeps_them_out_of_psychology():
    original = KernelState(minds={"npc": record(mind(), source(), minute=1)}, recovery=gap())
    raw = {KEY: original.model_dump(mode="json")}
    backup = deepcopy(raw)
    forked = load(
        SimpleNamespace(
            entity_states=lifecycle.fork(
                raw,
                {"m1": "copy1", "input": "copy-input", "reply": "copy-reply"},
                "copy",
            )
        )
    )
    assert raw == backup
    assert forked.recovery.pending_gap_turns == 1
    assert forked.recovery.recent[0].reply_id == "copy-reply"
    assert forked.recovery.recent[0].reply_revision is None
    assert forked.recovery.gap_cursors == {"npc": 1}
    assert forked.actors == {} and forked.memories == {}
    missing = load(SimpleNamespace(entity_states=lifecycle.fork(raw, {}, "copy")))
    assert missing.recovery.recent == []
    assert missing.recovery.gap_cursors == {"npc": 0}


def test_source_retraction_clears_gap_reference_and_clamps_historical_cutoff():
    recovery = gap()
    recovery.recent[0].reply_id = "m1"
    state = SimpleNamespace(
        entity_states={
            KEY: KernelState(
                minds={"npc": record(mind(), source(), minute=1)},
                recovery=recovery,
            ).model_dump()
        }
    )
    retract(state, "m1")
    saved = load(state)
    assert not saved.recovery.recent and saved.recovery.gap_cursors == {"npc": 0}
    # Counts remain conservative until a reviewed turn; edited ordinary prose
    # must not turn old psychological estimates back into current facts.
    assert saved.recovery.pending_gap_turns == 1


def test_diagnostic_window_is_bounded_without_discarding_canonical_history():
    host, _ = continuing()
    for index in range(12):
        turn = runtime.Turn(load(host.state), f"input-{index}")
        continuation.activate(turn, "analysis_failed")
        turn.simplified_text = f"Ordinary response {index}."
        host._chpm_turn = turn
        runtime.finish(
            host,
            SimpleNamespace(
                id=f"reply-{index}",
                session_id="session",
                role="assistant",
                content=turn.simplified_text,
                revision_id=None,
            ),
            completed=True,
        )
    saved = load(host.state)
    assert len(saved.recovery.recent) == 8
    assert saved.recovery.total_simplified_turns == 12
    assert saved.recovery.pending_gap_turns == 12
    assert saved.recovery.recent[0].reply_id == "reply-4"
    assert saved == KernelState.model_validate_json(saved.model_dump_json())


def test_simplified_reply_still_obeys_optimistic_save_fence():
    host, turn = continuing()
    continuation.activate(turn, "analysis_failed")
    turn.simplified_text = "Ordinary response."
    save(host.state, load(host.state), expected_revision=0)
    newer = deepcopy(host.state.entity_states)
    with pytest.raises(ChpmError, match="state changed"):
        runtime.finish(
            host,
            SimpleNamespace(
                id="reply",
                session_id="session",
                role="assistant",
                content=turn.simplified_text,
                revision_id=None,
            ),
            completed=True,
        )
    assert host.state.entity_states == newer


def test_public_badge_does_not_replay_private_psychological_journals():
    host, _ = continuing()
    # The status projection reads metadata only. Admission/load separately
    # reject invalid minds before any use in decisions or a save.
    host.state.entity_states[KEY]["minds"] = {"npc": {"invalid": "private"}}
    assert runtime.public_status(host.state)["module_version"] == "1.0.0"
    with pytest.raises(ValueError):
        load(host.state)


async def test_turn_snapshot_restores_continuation_counters_exactly(chpm_world):
    from sqlalchemy import select

    from backend.models.session_state import SessionState

    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(
                settings=Settings(mode="live", actor_ids=["NPC_NEW"]),
                recovery=gap(),
            ).model_dump(mode="json"),
        }
        await db.commit()
        snapshot = await capture(db, "portrait-session")
        before = load(state)
        modified = before.model_copy(deep=True)
        modified.recovery.pending_gap_turns = 7
        save(state, modified, expected_revision=before.revision)
        await db.flush()
        await restore(db, "portrait-session", snapshot)
        await db.refresh(state)
        assert load(state) == before
