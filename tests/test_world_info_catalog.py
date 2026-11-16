"""Large fictional catalogs stay paginated and aggregate in SQL, never in the client."""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import get_args
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import event, insert, select

from backend.engine.world_info import views
from backend.engine.world_info.parsing import parse_source
from backend.engine.world_info.query import entry_query
from backend.engine.world_info.schemas import EntryFilters, EntryUpdate
from backend.engine.world_info.types import EntryDraft, EntryKind, entry_hash, searchable_text
from backend.models.user import User
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource
from tests.conftest import TestSessionLocal, test_engine
from tests.test_world_info_schemas import update_body
from tests.test_world_info_views import portrait_world, view_world

__all__ = ["portrait_world", "view_world"]
SID = "portrait-session"
URL = f"/api/adventures/{SID}/world-info"


def _catalog_entry(index, source_id, revision_id, source_hash, plan):
    local = index % 1000
    passage = next(p for p in plan.batches[local // 4].passages if p.pointer != "/source")
    draft = EntryDraft(
        id=str(UUID(int=index + 1)),
        title=f"Record {index:05}",
        summary="An attributed source note.",
        group_name=f"Group {index % 120:03}" if index else "",
        kind=get_args(EntryKind)[index % 7],
        tags=["shared", f"Tag {index % 150:03}"],
        facts=[
            {
                "id": str(UUID(int=100000 + index)),
                "text": passage.text,
                "original_text": passage.text,
                "evidence": [
                    {
                        "passage_id": passage.id,
                        "pointer": passage.pointer,
                        "start": passage.start,
                        "end": passage.end,
                        "quote": passage.text,
                        "source_hash": source_hash,
                    }
                ],
            }
        ],
    )
    return draft.model_dump(mode="json") | {
        "user_id": "placeholder",
        "session_id": SID,
        "source_id": source_id,
        "source_revision_id": revision_id,
        "batch_index": local // 4,
        "ordinal": local % 4,
        "audience": "narrator_only",
        "known_by": [],
        "unresolved_known_by": [],
        "status": ("published", "draft", "archived", "draft")[index % 4],
        "version": 1,
        "edited": False,
        "search_text": searchable_text(draft),
        "content_hash": entry_hash(draft),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index),
    }


@pytest_asyncio.fixture
async def catalog_10000(portrait_world):
    content = json.dumps(
        {"source": 0, "statements": [f"Northern harbour statement {i}." for i in range(18000)]}
    )
    plan = parse_source(content, "json")
    assert len(plan.batches) >= 250
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User.id))
        for source_number in range(10):
            source_id, revision_id = (
                str(UUID(int=200000 + source_number)),
                str(UUID(int=300000 + source_number)),
            )
            raw = content.replace('"source": 0', f'"source": {source_number}', 1)
            digest = hashlib.sha256(raw.encode()).hexdigest()
            db.add(
                WorldInfoSource(
                    id=source_id,
                    user_id=owner,
                    session_id=SID,
                    title=f"Source {source_number:02}",
                    filename=f"notes-{source_number}.json",
                    format="json",
                    current_revision=1,
                    published_revision=1,
                )
            )
            await db.flush()
            db.add(
                WorldInfoRevision(
                    id=revision_id,
                    source_id=source_id,
                    user_id=owner,
                    session_id=SID,
                    number=1,
                    filename=f"notes-{source_number}.json",
                    format="json",
                    content=raw,
                    content_hash=digest,
                    input_bytes=len(raw.encode()),
                    input_characters=len(raw),
                    status="review",
                    cursor=len(plan.batches),
                    total_batches=len(plan.batches),
                    processed_characters=plan.character_offsets[-1],
                    facts_count=1000,
                    entries_count=1000,
                    processing_language="English",
                )
            )
            await db.flush()
            rows = [
                _catalog_entry(index, source_id, revision_id, digest, plan) | {"user_id": owner}
                for index in range(source_number * 1000, (source_number + 1) * 1000)
            ]
            await db.execute(insert(WorldInfoEntry), rows)
        await db.commit()
        return owner


async def test_10000_records_page_facets_and_overview_use_constant_size_sql_reads(catalog_10000):
    async with TestSessionLocal() as db:
        user = await db.get(User, catalog_10000)
        statements = []

        def record(_connection, _cursor, sql, _parameters, _context, _many):
            statements.append(sql)

        event.listen(test_engine.sync_engine, "before_cursor_execute", record)
        try:
            overview = await views.overview(db, user, SID)
            before_page = len(statements)
            page = await views.list_entries(
                db,
                user.id,
                SID,
                filters=EntryFilters(view="all", query="HARBOUR NORTHERN", sort="title_asc"),
                offset=9950,
                limit=50,
            )
            page_queries = len(statements) - before_page
            before_facets = len(statements)
            facets = await views.entry_facets(db, user.id, SID, EntryFilters(view="all"))
            facet_sql = statements[before_facets:]
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", record)
        assert overview.totals.entries == overview.totals.facts == 10000
        assert (
            overview.totals.active_entries,
            overview.totals.draft_entries,
            overview.totals.archived_entries,
        ) == (2500, 5000, 2500)
        assert overview.totals.sources == overview.totals.source_revisions == 10
        assert page.total == 10000 and len(page.entries) == 50 and page.next_offset is None
        assert [row.title for row in page.entries] == [f"Record {i:05}" for i in range(9950, 10000)]
        assert "evidence" not in page.model_dump_json() and len(page.model_dump_json()) < 100000
        assert facets.groups.total == 121 and facets.tags.total == 151 and facets.kinds.total == 7
        assert len(facets.groups.items) == len(facets.tags.items) == 100
        assert page_queries <= 3 and len(facet_sql) <= 7 and len(statements) <= 22
        assert not any(
            re.search(r"world_info_revisions\.content(?:\s|,)", sql) for sql in statements
        )
        assert not any("world_info_entries.facts" in sql for sql in facet_sql)
        filtered = await views.entry_facets(
            db, user.id, SID, EntryFilters(view="all"), facet_query="Group 119"
        )
        assert filtered.groups.total == 1 and filtered.groups.items[0].name == "Group 119"
        assert (
            await views.list_entries(db, user.id, SID, view="all", query="northern missing")
        ).total == 0


async def _label_records(db, ids):
    for identity, title, group, kind in zip(
        ids,
        ["Gamma", "Alpha", "Beta"],
        ["Coast", "", "Coast"],
        ["world_fact", "rumor", "news"],
        strict=True,
    ):
        row = await db.get(WorldInfoEntry, identity)
        row.title, row.group_name, row.kind, row.tags = title, group, kind, ["map"]
        row.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
            seconds={"Gamma": 2, "Alpha": 0, "Beta": 1}[title]
        )
        draft = EntryDraft.model_validate(
            {key: getattr(row, key) for key in EntryDraft.model_fields}
        )
        row.search_text, row.content_hash = searchable_text(draft), entry_hash(draft)
    await db.commit()


async def test_shared_filters_groups_tags_kind_allterms_and_stable_sorts(view_world):
    owner, _, _, _, active, old, current, *_ = view_world
    async with TestSessionLocal() as db:
        await _label_records(db, [active, old, current])
        selector = await entry_query(
            db,
            owner,
            SID,
            EntryFilters(
                view="all", group_name="Coast", tag="map", query="БУХТЫ МАЯК", sort="title_asc"
            ),
        )
        assert len(selector.column_descriptions) == 1
        assert [row.id for row in await db.scalars(selector)] == [current, active]
        page = await views.list_entries(
            db, owner, SID, filters=EntryFilters(view="all", group_name="", kind="rumor")
        )
        assert [row.id for row in page.entries] == [old]
        descending = await views.list_entries(
            db, owner, SID, filters=EntryFilters(view="all", tag="map", sort="title_desc")
        )
        assert [row.title for row in descending.entries] == ["Gamma", "Beta", "Alpha"]
        for order, expected in [
            ("oldest", ["Alpha", "Beta", "Gamma"]),
            ("newest", ["Gamma", "Beta", "Alpha"]),
            ("source", ["Gamma", "Alpha", "Beta"]),
        ]:
            ordered = await views.list_entries(
                db, owner, SID, filters=EntryFilters(view="all", tag="map", sort=order)
            )
            assert [row.title for row in ordered.entries] == expected
        facets = await views.entry_facets(
            db, owner, SID, EntryFilters(view="all", group_name="Coast", tag="map", kind="news")
        )
        assert {row.name for row in facets.groups.items} == {"", "Coast"}
        assert {row.name for row in facets.kinds.items} >= {"world_fact", "rumor", "news"}


async def test_saved_padded_group_names_remain_exactly_filterable(view_world):
    owner, _, _, _, active, *_ = view_world
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoEntry, active)
        row.group_name = " Coast "
        draft = EntryDraft.model_validate(
            {key: getattr(row, key) for key in EntryDraft.model_fields}
        )
        row.search_text, row.content_hash = searchable_text(draft), entry_hash(draft)
        await db.commit()
        page = await views.list_entries(
            db, owner, SID, filters=EntryFilters(view="all", group_name=" Coast ")
        )
        assert [item.id for item in page.entries] == [active]
        facets = await views.entry_facets(
            db, owner, SID, EntryFilters(view="all"), facet_query="Coast"
        )
        assert [item.name for item in facets.groups.items] == [" Coast "]


async def test_http_facets_route_precedes_entry_ids_and_scopes_all_selectors(
    auth_client, view_world
):
    _, _, _, _, active, old, current, *_ = view_world
    async with TestSessionLocal() as db:
        await _label_records(db, [active, old, current])
    response = await auth_client.get(
        URL + "/entries/facets", params={"view": "all", "facet_query": "Coast"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["groups"] == {"items": [{"name": "Coast", "count": 2}], "total": 1}
    page = await auth_client.get(
        URL + "/entries",
        params={
            "view": "all",
            "group_name": "Coast",
            "tag": "map",
            "kind": "world_fact",
            "sort": "oldest",
        },
    )
    assert page.status_code == 200 and [row["id"] for row in page.json()["entries"]] == [active]
    for params in [{"sort": "unsafe"}, {"group_name": "x" * 81}, {"limit": 101}, {"tag": ""}]:
        assert (await auth_client.get(URL + "/entries", params=params)).status_code == 422
    assert (
        await auth_client.get(URL + "/entries/facets", params={"source_revision_id": "foreign"})
    ).status_code == 404
    assert (
        await auth_client.get("/api/adventures/other-session/world-info/entries/facets")
    ).status_code == 404


def test_group_edit_default_preserves_legacy_and_empty_string_explicitly_clears():
    body = update_body()
    assert EntryUpdate.model_validate(body).group_name is None
    assert EntryUpdate.model_validate(body | {"group_name": ""}).group_name == ""
    assert len(EntryUpdate.model_validate(body | {"group_name": "g" * 80}).group_name) == 80
    with pytest.raises(ValueError):
        EntryUpdate.model_validate(body | {"group_name": "g" * 81})
