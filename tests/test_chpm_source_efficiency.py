"""Long-lived observers do not rehash a message or replay a ledger per excerpt."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.engine.chpm import host_adapter, host_sources, host_state
from backend.engine.chpm.core.history import count
from backend.engine.chpm.host_state import record_many
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.schema import KernelState, Perception
from tests.test_chpm_host_state import mind, source
from tests.test_chpm_kernel import observation
from tests.test_chpm_runtime import manager


async def test_reconcile_hashes_each_message_once_but_checks_every_quote():
    text = " ".join(f"Exact observation {n}." for n in range(32))
    entries = [
        source(text=f"Exact observation {n}.").model_copy(update={"content_hash": digest(text)})
        for n in range(32)
    ]
    saved = record_many(mind(), entries, minute=1)
    row = SimpleNamespace(id="m1", role="assistant", revision_id=None, content=text)
    host = SimpleNamespace(
        game_id="session", db=SimpleNamespace(scalars=AsyncMock(return_value=[row]))
    )
    with patch.object(host_sources, "digest", wraps=digest) as hashing:
        assert await host_sources.reconcile(host, saved) is saved
    assert hashing.call_count == 1
    # Edits remain invalidating; this optimization never caches beyond the query.
    row.content = "Changed message."
    assert not (await host_sources.reconcile(host, saved)).sources


def test_reviewed_speech_is_validated_as_one_atomic_batch_with_identical_evidence():
    turn = SimpleNamespace(minds={"npc": mind()})
    quotes = [f"Exact observation {n}." for n in range(12)]
    reply = SimpleNamespace(id="reply", revision_id=None, content=" ".join(quotes))
    entries = [
        SimpleNamespace(
            source_role="assistant",
            source_message_id=reply.id,
            source_revision_id=None,
            source_hash=digest(reply.content),
            speaker_id="npc",
            quote=quote,
        )
        for quote in quotes
    ]
    with patch.object(host_state, "restore", wraps=host_state.restore) as replay:
        finished = host_adapter.finish(turn, reply, entries, "npc", minute=1)
    assert count(finished.snapshot) == len(quotes)
    assert [s.text for s in finished.sources.values()] == quotes
    assert replay.call_count == 1
    assert not turn.minds["npc"].sources


async def test_same_turn_causal_reconciliation_is_reused_without_a_second_query(monkeypatch):
    host, actor = manager()
    original = mind()
    turn = SimpleNamespace(
        initial=KernelState(minds={"npc": original}),
        minds={},
        present_names={"npc": "Rin"},
        perceptions={"npc": Perception(actor_id="npc", quotes=[])},
        reconciled_minds={"npc": original},
    )
    checked = AsyncMock(side_effect=AssertionError("Already checked this preparation"))
    monkeypatch.setattr(host_sources, "reconcile", checked)
    prepared = await host_adapter.prepare(host, turn, actor, observation())
    assert prepared.genesis == original.genesis
    assert any(src.kind == "host_frame" for src in prepared.sources.values())
    checked.assert_not_awaited()
