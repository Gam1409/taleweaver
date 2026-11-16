"""Independent mocked HTTP probes for scalable WorldInfo publication boundaries."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from backend.engine.world_info import entries, jobs
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource
from tests.conftest import TestSessionLocal
from tests.test_world_info_api import URL, corpus_api, portrait_world
from tests.test_world_info_bulk import request

__all__ = ["corpus_api", "portrait_world"]


async def preview(client, body):
    result = await client.post(URL + "/entries/bulk/preview", json=body)
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.asyncio
async def test_live_publication_change_invalidates_previously_previewed_collection(
    auth_client, corpus_api
):
    _, corpus = corpus_api
    body = request(corpus, action="publish", group_name=None)
    first = await preview(auth_client, body)
    source_id = corpus["sources"][0]["id"]
    upload = await auth_client.post(
        URL + f"/sources/{source_id}/revisions",
        files={"file": ("replacement.md", "The coast has a lighthouse.")},
        data={"expected_version": "2"},
    )
    assert upload.status_code == 201, upload.text
    stale = await auth_client.post(
        URL + "/entries/bulk/apply", json=body | {"selection_hash": first["selection_hash"]}
    )
    assert stale.status_code == 409, stale.text
    async with TestSessionLocal() as db:
        rows = list(await db.scalars(select(WorldInfoEntry)))
        assert all(row.version == 1 and row.status == "published" for row in rows)


@pytest.mark.asyncio
async def test_evidence_revalidated_before_any_entry_is_published(auth_client, corpus_api):
    _, corpus = corpus_api
    async with TestSessionLocal() as db:
        for row in await db.scalars(select(WorldInfoEntry)):
            row.status = "draft"
        await db.commit()
    body = request(corpus, action="publish", group_name=None)
    selected = await preview(auth_client, body)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoEntry, corpus["entries"][1]["id"])
        facts = deepcopy(row.facts)
        facts[0]["evidence"][0]["quote"] = "X" * len(facts[0]["evidence"][0]["quote"])
        row.facts = facts
        await db.commit()
    rejected = await auth_client.post(
        URL + "/entries/bulk/apply", json=body | {"selection_hash": selected["selection_hash"]}
    )
    assert rejected.status_code == 422, rejected.text
    async with TestSessionLocal() as db:
        rows = list(await db.scalars(select(WorldInfoEntry)))
        assert all(row.status == "draft" and row.version == 1 for row in rows)
        source = await db.get(WorldInfoSource, corpus["sources"][0]["id"])
        assert source.version == 2


@pytest.mark.asyncio
async def test_bulk_blocks_active_processing_but_explicit_reviewed_subset_can_publish(
    auth_client, corpus_api
):
    _, corpus = corpus_api
    rid = corpus["revisions"][0]["id"]
    async with TestSessionLocal() as db:
        revision = await db.get(WorldInfoRevision, rid)
        revision.status = "processing"
        await db.commit()
    body = request(corpus, action="publish", group_name=None)
    blocked = await auth_client.post(URL + "/entries/bulk/preview", json=body)
    assert (
        blocked.status_code == 409
        and "Finish or stop source processing" in blocked.json()["detail"]
    )
    one = corpus["entries"][0]
    explicit = await auth_client.post(
        URL + "/publish",
        json={
            "revision_id": rid,
            "source_version": 2,
            "entries": [{"id": one["id"], "version": 1}],
        },
    )
    assert explicit.status_code == 200, explicit.text


@pytest.mark.asyncio
async def test_publication_parses_source_once_and_never_uses_per_entry_parser(
    auth_client, corpus_api, monkeypatch
):
    _, corpus = corpus_api
    body = request(corpus, action="publish", group_name=None)
    selected = await preview(auth_client, body)
    parse = Mock(wraps=jobs.parse_source)
    monkeypatch.setattr(jobs, "parse_source", parse)
    monkeypatch.setattr(
        entries, "parse_source", Mock(side_effect=AssertionError("Repeated source parse"))
    )
    applied = await auth_client.post(
        URL + "/entries/bulk/apply", json=body | {"selection_hash": selected["selection_hash"]}
    )
    assert applied.status_code == 200, applied.text
    assert parse.call_count == 1
