"""Escaped evidence and audience metadata share one producer/consumer quota."""

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from backend.engine.world_info import capacity, jobs, limits, queue, results, worker
from backend.engine.world_info.parsing import parse_source
from backend.engine.world_info.portable_schema import PortableEntry
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision
from tests.conftest import TestSessionLocal
from tests.test_world_info_jobs import portrait_world, seed_revision, world_info_owner
from tests.test_world_info_worker import fixture_entry

__all__ = ["portrait_world", "world_info_owner"]


async def test_canonical_bytes_match_preflush_database_and_portable_defaults(world_info_owner):
    content = "Архив хранит сведения о маяке."
    revision_id = await seed_revision(world_info_owner, content=content)
    claim = await queue.claim_next("portrait-session", world_info_owner)
    plan = parse_source(content, "md")
    draft = fixture_entry(revision_id, plan.source_hash, plan.batches[0])
    row = results._new_entry(claim, draft, 0)
    before = capacity.entry_bytes(row)
    async with TestSessionLocal() as db:
        db.add(row)
        await db.commit()
        assert capacity.entry_bytes(row) == before
        portable = PortableEntry.model_validate(
            {name: getattr(row, name) for name in PortableEntry.model_fields if hasattr(row, name)}
        )
        assert capacity.entry_bytes(portable) == before
        assert capacity.entry_bytes(portable.model_dump(mode="json")) == before


async def test_exact_escaped_byte_boundary_counts_evidence_and_acl(world_info_owner, monkeypatch):
    content = "Архив хранит сведения о маяке."
    revision_id = await seed_revision(world_info_owner, content=content)
    claim = await queue.claim_next("portrait-session", world_info_owner)
    plan = parse_source(content, "md")
    row = results._new_entry(
        claim, fixture_entry(revision_id, plan.source_hash, plan.batches[0]), 0
    )
    baseline = capacity.corpus_entry_bytes([row])
    row.audience = "restricted"
    row.known_by = ["исследователь"]
    row.unresolved_known_by = []
    reserved = capacity.corpus_entry_bytes([row])
    assert row.unresolved_known_by == []
    row.unresolved_known_by = ["исследователь"]
    escaped = capacity.corpus_entry_bytes([row])
    assert reserved == escaped
    assert escaped > baseline + len("исследователь".encode()) * 2
    monkeypatch.setattr(limits, "MAX_SESSION_ENTRY_BYTES", escaped)
    capacity.validate_entry_capacity([row])
    monkeypatch.setattr(limits, "MAX_SESSION_ENTRY_BYTES", escaped - 1)
    with pytest.raises(capacity.CapacityError):
        capacity.validate_entry_capacity([row])


async def test_quota_failure_preserves_existing_records_then_explicit_resume_can_finish(
    world_info_owner, monkeypatch
):
    owner = world_info_owner
    first_id = await seed_revision(owner)
    calls = []

    async def extract(user, sid, rid, source_hash, batch, references, **kwargs):
        await kwargs["before_request"]()
        calls.append(rid)
        return [fixture_entry(rid, source_hash, batch)]

    monkeypatch.setattr(worker, "extract_batch", extract)
    await worker._run("portrait-session", owner)
    revision_id = await seed_revision(owner)
    claim = await queue.claim_next("portrait-session", owner)
    async with TestSessionLocal() as db:
        revision = await db.get(WorldInfoRevision, revision_id)
        plan = parse_source(revision.content, "md")
        proposed = results._new_entry(
            claim, fixture_entry(revision_id, plan.source_hash, plan.batches[0]), 0
        )
        old = await db.scalar(select(WorldInfoEntry))
        previous_hash = old.content_hash
        required = capacity.corpus_entry_bytes([old, proposed])
    monkeypatch.setattr(limits, "MAX_SESSION_ENTRY_BYTES", required - 1)
    await worker.process_claim(claim)
    async with TestSessionLocal() as db:
        revision = await db.get(WorldInfoRevision, revision_id)
        assert (revision.status, revision.last_error_code, revision.cursor) == (
            "failed",
            "storage_limit",
            0,
        )
        assert revision.attempts == 1 and revision.facts_count == revision.entries_count == 0
        old = await db.scalar(select(WorldInfoEntry))
        assert old.content_hash == previous_hash
        assert (await db.get(WorldInfoRevision, first_id)).entries_count == 1
        assert await db.scalar(select(func.count(WorldInfoEntry.id))) == 1
        monkeypatch.setattr(limits, "MAX_SESSION_ENTRY_BYTES", required)
        await jobs.start_processing(db, owner, "portrait-session", revision_id, 1)
        await db.commit()
    await worker._run("portrait-session", owner)
    assert calls == [first_id, revision_id, revision_id]
    async with TestSessionLocal() as db:
        revision = await db.get(WorldInfoRevision, revision_id)
        assert revision.status == "review" and revision.cursor == revision.entries_count == 1
        rows = list(await db.scalars(select(WorldInfoEntry)))
        assert capacity.corpus_entry_bytes(rows) == required


def test_missing_metadata_cannot_bypass_storage_measurement():
    with pytest.raises(capacity.CapacityError):
        capacity.entry_bytes(SimpleNamespace())
