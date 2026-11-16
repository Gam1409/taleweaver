"""Long RP recall must not decode unrelated archived journal blocks."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.engine.memory_rag.documents import _journal_documents
from backend.engine.memory_rag.recall_sources import _journal_source_ids
from backend.engine.npc_journal import archive
from backend.engine.npc_journal.lifecycle import remap_journal
from backend.engine.npc_journal.records import journal_of, memory_context


def npc_with_history(count=2000):
    entries = [
        {
            "id": f"entry-{n}",
            "message_id": f"message-{n}",
            "category": "event",
            "topic": f"topic-{n}",
            "source": "observed",
            "text": f"Fact {n}: " + "recorded detail " * 25,
            "evidence": f"Fact {n}.",
            "game_minute": n,
        }
        for n in range(count)
    ]
    journal = archive.compact({"version": 1, "entries": entries})
    return SimpleNamespace(id="LINA", name="Lina", metadata_json={"npc_journal": journal}), entries


def counter(monkeypatch):
    original = archive.zlib.decompressobj
    calls = []

    def decode(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(archive.zlib, "decompressobj", decode)
    return calls


def test_recent_source_ids_do_not_expand_cold_archive(monkeypatch):
    npc, _ = npc_with_history()
    calls = counter(monkeypatch)
    assert _journal_source_ids([npc], 3) == {"message-1997", "message-1998", "message-1999"}
    assert calls == []


def test_old_vector_hit_reads_only_its_matching_archive_block(monkeypatch):
    npc, _ = npc_with_history()
    message = SimpleNamespace(
        id="message-0",
        role="assistant",
        scene_id="LAB",
        content="Fact 0.",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    calls = counter(monkeypatch)
    docs = _journal_documents(
        SimpleNamespace(session_id="S", template_id="T"), "U", npc, {message.id: message}
    )
    assert len(docs) == 1 and docs[0].source_message_ids == ["message-0"]
    assert docs[0].game_minute == 0
    assert len(calls) == 1


def test_bounded_character_context_is_identical_without_full_archive_expansion(monkeypatch):
    npc, _ = npc_with_history()
    calls = counter(monkeypatch)
    context = memory_context(npc)
    assert len(context) == 1600
    assert context.index("Fact 1999:") < context.index("Fact 1998:") < context.index("Fact 1997:")
    assert "Fact 0:" not in context
    assert calls == []


def test_archive_and_copy_keep_every_record_and_rebuild_source_hints():
    npc, entries = npc_with_history()
    assert journal_of(npc, full=True)["entries"] == entries
    mapping = {f"message-{n}": f"copy-{n}" for n in range(2000)}
    copied = SimpleNamespace(id="LINA", metadata_json=remap_journal(npc.metadata_json, mapping))
    assert len(journal_of(copied, full=True)["entries"]) == 2000
    assert _journal_source_ids([copied], 2) == {"copy-1999", "copy-1998"}
    assert npc.metadata_json["npc_journal"]["entries"][-1]["message_id"] == "message-1999"


def test_missing_or_stale_hints_never_make_a_source_disappear(monkeypatch):
    npc, entries = npc_with_history()
    legacy = deepcopy(npc.metadata_json)
    legacy["npc_journal"].pop("archive_index", None)
    assert journal_of(SimpleNamespace(metadata_json=legacy), full=True)["entries"] == entries
    hints = npc.metadata_json["npc_journal"].get("archive_index")
    if hints:
        hints[0]["chunk_hash"] = "stale"
    message = SimpleNamespace(
        id="message-0",
        role="assistant",
        scene_id="LAB",
        content="Fact 0.",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    docs = _journal_documents(
        SimpleNamespace(session_id="S", template_id="T"), "U", npc, {message.id: message}
    )
    assert len(docs) == 1


def test_incomplete_source_hints_fall_back_to_the_canonical_chunk():
    from backend.engine.npc_journal.reading import entries

    npc, _ = npc_with_history()
    npc.metadata_json["npc_journal"]["archive_index"][0]["messages"] = []
    selected = list(entries(npc, message_ids={"message-0"}))
    assert len(selected) == 1 and selected[0]["message_id"] == "message-0"
