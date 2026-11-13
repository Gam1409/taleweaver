"""Server-selected collection changes stay atomic and independent of browser pages."""

from copy import deepcopy

from sqlalchemy import select

from backend.engine.world_info.portability import export_world_info
from backend.models.world_info import WorldInfoEntry
from tests.conftest import TestSessionLocal
from tests.test_world_info_api import SID, URL, corpus_api, portrait_world, update_payload

__all__ = ["corpus_api", "portrait_world"]


def request(corpus, **changes):
    return {
        "action": "set_group",
        "group_name": "Coastal history",
        "filters": {
            "view": "all",
            "source_revision_id": corpus["revisions"][0]["id"],
        },
    } | changes


async def preview(auth_client, payload):
    response = await auth_client.post(URL + "/entries/bulk/preview", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


async def test_bulk_group_and_tags_preserve_all_provenance_and_scopes(auth_client, corpus_api):
    owner, corpus = corpus_api
    body = request(corpus)
    proposed = await preview(auth_client, body)
    assert proposed["count"] == proposed["facts_count"] == 2
    assert proposed["active_count"] == 2 and len(proposed["sample"]) == 2
    async with TestSessionLocal() as db:
        assert all(not row.group_name for row in await db.scalars(select(WorldInfoEntry)))
    applied = await auth_client.post(
        URL + "/entries/bulk/apply", json=body | {"selection_hash": proposed["selection_hash"]}
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["changed"] == 2
    tagged = request(corpus, action="add_tags", group_name=None, tags=["lighthouse"])
    proposed = await preview(auth_client, tagged)
    result = await auth_client.post(
        URL + "/entries/bulk/apply", json=tagged | {"selection_hash": proposed["selection_hash"]}
    )
    assert result.status_code == 200, result.text
    async with TestSessionLocal() as db:
        saved = await export_world_info(db, SID, owner)
        for row, original in zip(saved["entries"], corpus["entries"], strict=True):
            assert row["group_name"] == "Coastal history"
            assert row["tags"] == ["harbor", "lighthouse"]
            assert row["facts"] == original["facts"]
            assert row["known_by"] == original["known_by"]
            assert row["audience"] == original["audience"]


async def test_changed_selection_and_action_require_a_new_preview(auth_client, corpus_api):
    _, corpus = corpus_api
    body = request(corpus)
    proposed = await preview(auth_client, body)
    entry = corpus["entries"][0]
    updated = await auth_client.put(
        URL + f"/entries/{entry['id']}",
        json=update_payload(entry) | {"summary": "Updated navigation summary."},
    )
    assert updated.status_code == 200
    stale = await auth_client.post(
        URL + "/entries/bulk/apply", json=body | {"selection_hash": proposed["selection_hash"]}
    )
    assert stale.status_code == 409
    proposed = await preview(auth_client, body)
    changed_parameters = await auth_client.post(
        URL + "/entries/bulk/apply",
        json=body
        | {"group_name": "A different collection", "selection_hash": proposed["selection_hash"]},
    )
    assert changed_parameters.status_code == 409
    async with TestSessionLocal() as db:
        assert all(not row.group_name for row in await db.scalars(select(WorldInfoEntry)))


async def test_bulk_tag_limit_failure_never_applies_partial_edits(auth_client, corpus_api):
    _, corpus = corpus_api
    entry = corpus["entries"][0]
    response = await auth_client.put(
        URL + f"/entries/{entry['id']}",
        json=update_payload(entry) | {"tags": [f"tag-{i}" for i in range(12)]},
    )
    assert response.status_code == 200
    body = request(corpus, action="add_tags", group_name=None, tags=["extra"])
    proposed = await preview(auth_client, body)
    failed = await auth_client.post(
        URL + "/entries/bulk/apply", json=body | {"selection_hash": proposed["selection_hash"]}
    )
    assert failed.status_code == 422, failed.text
    other = (await auth_client.get(URL + f"/entries/{corpus['entries'][1]['id']}")).json()
    assert other["version"] == 1 and other["tags"] == ["harbor"]


async def test_bulk_selection_is_owner_scoped(auth_client, corpus_api):
    body = request(corpus_api[1])
    foreign = await auth_client.post(
        "/api/adventures/other-session/world-info/entries/bulk/preview", json=body
    )
    assert foreign.status_code == 404
    body["filters"]["source_revision_id"] = "unknown"
    assert (await auth_client.post(URL + "/entries/bulk/preview", json=body)).status_code == 404


async def test_bulk_publish_has_the_same_revision_and_evidence_contract(auth_client, corpus_api):
    owner, corpus = corpus_api
    async with TestSessionLocal() as db:
        rows = list(await db.scalars(select(WorldInfoEntry)))
        for row in rows:
            row.status = "draft"
        await db.commit()
    body = request(corpus, action="publish", group_name=None)
    proposed = await preview(auth_client, body)
    response = await auth_client.post(
        URL + "/entries/bulk/apply", json=body | {"selection_hash": proposed["selection_hash"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["changed"] == 2
    current = (await auth_client.get(URL + "/entries?view=active")).json()
    assert current["total"] == 2
    async with TestSessionLocal() as db:
        exported = await export_world_info(db, SID, owner)
        assert exported["sources"][0]["version"] == 3
        assert all(row["status"] == "published" for row in exported["entries"])


async def test_legacy_text_edit_preserves_group(auth_client, corpus_api):
    entry = corpus_api[1]["entries"][0]
    payload = update_payload(entry) | {"group_name": "Places"}
    first = await auth_client.put(URL + f"/entries/{entry['id']}", json=payload)
    assert first.status_code == 200
    payload = deepcopy(payload)
    payload.pop("group_name")
    payload["version"] = 2
    saved = await auth_client.put(URL + f"/entries/{entry['id']}", json=payload)
    assert saved.status_code == 200
    assert saved.json()["group_name"] == "Places"
