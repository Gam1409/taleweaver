"""Owner-scoped real SQL projections; no model, embedding or mutation requests."""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from backend.engine.world_info import views
from backend.engine.world_info.parsing import parse_source
from backend.engine.world_info.types import EntryDraft, Evidence, Fact, entry_hash, searchable_text
from backend.engine.world_info.view_records import ViewIntegrityError, ViewNotFoundError
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState
from backend.models.user import User
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


def revision(source, number, *, status="review"):
    content = "The harbour beacon overlooks the coast."
    plan = parse_source(content, "md")
    return WorldInfoRevision(
        id=str(uuid4()),
        source_id=source.id,
        session_id=source.session_id,
        user_id=source.user_id,
        number=number,
        filename=f"notes-v{number}.md",
        format="md",
        content=content,
        content_hash=plan.source_hash,
        input_bytes=plan.bytes,
        input_characters=plan.characters,
        status=status,
        cursor=1 if status == "review" else 0,
        total_batches=1,
        processing_language="English",
        facts_count=2,
        entries_count=2,
        run_token="private-run-token",
        lease_token="private-lease-token",
    )


def entry(source, revision, ordinal, *, status="draft", title="港の灯台"):
    draft = EntryDraft(
        id=str(uuid4()),
        title=title,
        facts=[
            Fact(
                id=str(uuid4()),
                text="Маяк у бухты.",
                original_text="Маяк у бухты.",
                evidence=[
                    Evidence(
                        passage_id="p0",
                        start=0,
                        end=10,
                        quote="The harbou",
                        source_hash=revision.content_hash,
                    )
                ],
            )
        ],
    )
    return WorldInfoEntry(
        id=draft.id,
        source_id=source.id,
        source_revision_id=revision.id,
        session_id=source.session_id,
        user_id=source.user_id,
        batch_index=0,
        ordinal=ordinal,
        title=draft.title,
        summary=draft.summary,
        facts=[fact.model_dump(mode="json") for fact in draft.facts],
        tags=[],
        relations=[],
        kind=draft.kind,
        audience="narrator_only",
        known_by=[],
        status=status,
        search_text=searchable_text(draft),
        content_hash=entry_hash(draft),
    )


@pytest_asyncio.fixture
async def view_world(portrait_world):
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        source = WorldInfoSource(
            id=str(uuid4()),
            user_id=session.user_id,
            session_id=session.id,
            title="Coastal records",
            filename="notes-v2.md",
            format="md",
            current_revision=2,
            published_revision=1,
        )
        db.add(source)
        await db.flush()
        first, second = revision(source, 1), revision(source, 2, status="failed")
        db.add_all([first, second])
        await db.flush()
        active = entry(source, first, 0, status="published")
        old_draft = entry(source, first, 1, title="Earlier draft")
        current = entry(source, second, 0, title="Latest draft")
        inactive_published = entry(source, second, 1, status="published", title="Not active")
        db.add_all([active, old_draft, current, inactive_published])
        await db.commit()
        return (
            session.user_id,
            source.id,
            first.id,
            second.id,
            active.id,
            old_draft.id,
            current.id,
            inactive_published.id,
        )


async def test_overview_counts_exact_active_revision_and_never_exposes_job_tokens(view_world):
    owner, source_id, first_id, second_id, *_ = view_world
    async with TestSessionLocal() as db:
        user = await db.get(User, owner)
        result = await views.overview(db, user, "portrait-session")
        source = result.sources[0]
        assert source.id == source_id and source.job.id == second_id
        assert source.published_revision_id == first_id
        assert (source.active_entries, source.draft_entries, source.revision_count) == (1, 2, 2)
        assert (source.job.facts_count, source.job.entries_count) == (2, 2)
        assert source.job.can_resume and not source.job.can_start and not source.job.can_cancel
        assert [(row.id, row.name) for row in result.characters] == [("NPC_NEW", "Lina")]
        payload = result.model_dump_json()
        assert "private-run-token" not in payload and "private-lease-token" not in payload
        assert '"content"' not in payload and '"facts":[' not in payload
        assert result.limits.max_known_by == 32 and not result.index.enabled
        assert result.limits.max_entry_title_characters == 160
        assert result.limits.max_entry_summary_characters == 500
        assert result.limits.max_fact_characters == 500
        assert result.limits.max_relation_note_characters == 160


async def test_foreign_owner_and_revision_filters_are_unavailable(view_world):
    owner, source_id, _, second_id, *_ = view_world
    async with TestSessionLocal() as db:
        with pytest.raises(ViewNotFoundError):
            await views.list_entries(db, "foreign", "portrait-session", view="all")
        with pytest.raises(ViewNotFoundError):
            await views.list_entries(
                db, owner, "portrait-session", source_revision_id="foreign-revision"
            )
        row = await db.get(WorldInfoRevision, second_id)
        row.user_id = "foreign"
        await db.commit()
        with pytest.raises(ViewNotFoundError):
            await views.revision_view(db, row)
        source = await db.get(WorldInfoSource, source_id)
        with pytest.raises(ViewIntegrityError):
            await views.source_view(db, source)


async def test_review_active_all_and_historical_revision_filters_are_distinct(view_world):
    owner, _, first_id, _, active_id, old_id, current_id, *_ = view_world
    async with TestSessionLocal() as db:
        review = await views.list_entries(db, owner, "portrait-session")
        active = await views.list_entries(db, owner, "portrait-session", view="active")
        all_rows = await views.list_entries(db, owner, "portrait-session", view="all")
        old_review = await views.list_entries(
            db, owner, "portrait-session", source_revision_id=first_id
        )
        assert [row.id for row in review.entries] == [current_id]
        assert [row.id for row in active.entries] == [active_id]
        assert all_rows.total == 4 and sum(row.is_active for row in all_rows.entries) == 1
        assert [row.id for row in old_review.entries] == [old_id]
        page = await views.list_entries(db, owner, "portrait-session", view="all", limit=2)
        next_page = await views.list_entries(
            db, owner, "portrait-session", view="all", offset=page.next_offset, limit=2
        )
        assert page.next_offset == 2 and next_page.next_offset is None
        assert {row.id for row in page.entries}.isdisjoint(row.id for row in next_page.entries)


async def test_unicode_sizes_follow_current_rows_without_restarting_processing(view_world):
    _, _, first_id, _, active_id, old_id, *_ = view_world
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, first_id)
        job = await views.revision_view(db, row)
        texts = list(
            await db.scalars(
                select(WorldInfoEntry.search_text).where(
                    WorldInfoEntry.source_revision_id == first_id
                )
            )
        )
        assert job.entries_characters == sum(map(len, texts))
        assert job.entries_bytes == sum(len(text.encode("utf-8")) for text in texts)
        assert job.entries_bytes > job.entries_characters
        active = await db.get(WorldInfoEntry, active_id)
        detail = await views.entry_detail(db, active)
        assert detail.character_count == len(active.search_text)
        assert detail.byte_count == len(active.search_text.encode())
        assert detail.source_filename == "notes-v1.md" and detail.source_revision_number == 1
        await db.execute(delete(WorldInfoEntry).where(WorldInfoEntry.id == old_id))
        row.entries_count -= 1
        row.facts_count -= 1
        await db.commit()
        after = await views.revision_view(db, row)
        assert after.entries_characters == detail.character_count
        assert (after.facts_count, after.entries_count, after.cursor) == (1, 1, 1)


async def test_index_state_uses_current_session_and_existing_global_settings(view_world):
    owner, *_ = view_world
    async with TestSessionLocal() as db:
        user = await db.get(User, owner)
        db.add(
            MemoryIndexState(
                session_id="portrait-session",
                user_id=owner,
                status="paused",
                paused=True,
                desired_revision=5,
                indexed_revision=2,
            )
        )
        db.add(
            MemoryIndexState(
                session_id="other-session",
                user_id="another-owner",
                status="ready",
                desired_revision=90,
                indexed_revision=90,
            )
        )
        await db.commit()
        disabled = await views.index_state(db, user, "portrait-session")
        assert not disabled.enabled and disabled.status == "disabled" and disabled.paused
        user.llm_settings = {"memory_rag": {"enabled": True}}
        await db.commit()
        enabled = await views.index_state(db, user, "portrait-session")
        assert enabled.enabled and (enabled.desired_revision, enabled.indexed_revision) == (5, 2)
        assert enabled.status == "paused"
        with pytest.raises(ViewNotFoundError):
            await views.index_state(db, user, "other-session")


async def test_literal_query_search_is_unicode_aware_and_cannot_expand_wildcards(view_world):
    owner, _, _, _, active_id, *_ = view_world
    async with TestSessionLocal() as db:
        found = await views.list_entries(db, owner, "portrait-session", view="active", query="МАЯК")
        assert [row.id for row in found.entries] == [active_id]
        for literal in ("%", "_", "' OR 1=1 --"):
            assert (
                await views.list_entries(db, owner, "portrait-session", view="all", query=literal)
            ).total == 0


async def test_source_revision_content_is_explicit_and_old_revisions_cannot_control_jobs(
    view_world,
):
    _, source_id, first_id, second_id, *_ = view_world
    async with TestSessionLocal() as db:
        source = await db.get(WorldInfoSource, source_id)
        detail = await views.source_detail(db, source)
        assert [job.id for job in detail.revisions] == [second_id, first_id]
        old = await db.get(WorldInfoRevision, first_id)
        old.status = "uploaded"
        old.cursor = 0
        old.last_error_code = "provider private diagnostic sentinel"
        await db.commit()
        job = await views.revision_view(db, old)
        assert not job.can_start and not job.can_resume and not job.can_cancel
        assert job.last_error_code == "processing_failed"
        content = await views.revision_content(db, old)
        assert content.content == old.content and content.filename == "notes-v1.md"
        pair = await views.revision_detail(db, old)
        assert pair.revision.id == first_id and pair.source.job.id == second_id


async def test_invalid_saved_entry_errors_do_not_echo_source_or_fact_text(view_world):
    _, _, _, _, active_id, *_ = view_world
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoEntry, active_id)
        row.facts = [{"unexpected": "fictional private diagnostic sentinel"}]
        await db.commit()
        with pytest.raises(ViewIntegrityError) as error:
            await views.entry_detail(db, row)
        assert "sentinel" not in str(error.value)


async def test_retained_unresolved_recipients_are_visible_without_automatic_rebinding(view_world):
    _, _, _, _, active_id, *_ = view_world
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoEntry, active_id)
        row.audience = "restricted"
        row.known_by = ["absent-npc"]
        row.unresolved_known_by = ["absent-npc"]
        await db.commit()
        detail = await views.entry_detail(db, row)
        assert detail.known_by == detail.unresolved_known_by == ["absent-npc"]
        assert row.unresolved_known_by == ["absent-npc"]


async def test_decoded_json_progress_can_exceed_original_source_characters(view_world):
    owner, *_ = view_world
    async with TestSessionLocal() as db:
        source = WorldInfoSource(
            id=str(uuid4()),
            user_id=owner,
            session_id="portrait-session",
            title="Numeric source",
            filename="number.json",
            format="json",
        )
        db.add(source)
        await db.flush()
        row = revision(source, 1)
        plan = parse_source("1e2", "json")
        row.content = "1e2"
        row.format = "json"
        row.filename = "number.json"
        row.content_hash = plan.source_hash
        row.input_bytes = plan.bytes
        row.input_characters = plan.characters
        row.processed_characters = sum(len(p.text) for b in plan.batches for p in b.passages)
        row.facts_count = row.entries_count = 0
        db.add(row)
        await db.commit()
        job = await views.revision_view(db, row)
        assert (job.processed_characters, job.input_characters) == (5, 3)
        assert job.entries_count == job.entries_bytes == job.entries_characters == 0
        assert (await views.source_view(db, source)).published_revision_id is None


async def test_other_session_source_and_entries_never_enter_owner_overview(view_world):
    owner, source_id, *_ = view_world
    async with TestSessionLocal() as db:
        foreign = WorldInfoSource(
            id=str(uuid4()),
            user_id="another-owner",
            session_id="other-session",
            title="Another source",
            filename="other.md",
            format="md",
        )
        db.add(foreign)
        await db.flush()
        other = revision(foreign, 1)
        db.add(other)
        await db.flush()
        db.add(entry(foreign, other, 0, status="published"))
        await db.commit()
        user = await db.get(User, owner)
        overview = await views.overview(db, user, "portrait-session")
        assert [source.id for source in overview.sources] == [source_id]
        rows = await views.list_entries(db, owner, "portrait-session", view="all")
        assert rows.total == 4 and all(row.source_id == source_id for row in rows.entries)
