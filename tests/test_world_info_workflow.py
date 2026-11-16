"""Actual HTTP, extraction, durable processing and SQL recall form one workflow."""

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy import inspect, select

from backend.api.routes.adventures import world_info, world_info_entries
from backend.core.llm_router import GameMasterLLM
from backend.engine.memory_rag import retrieval
from backend.engine.memory_rag.prompts import recall_block
from backend.engine.world_info import worker
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision
from tests.conftest import TestSessionLocal
from tests.test_world_info_jobs import portrait_world, world_info_owner

__all__ = ["portrait_world", "world_info_owner"]
SID = "portrait-session"
URL = f"/api/adventures/{SID}/world-info"
QUOTE = "The lighthouse overlooks the harbour."
CORRECTED = "Harbour lighthouse stands on the eastern cliff."


def columns(row):
    return deepcopy({column.key: getattr(row, column.key) for column in inspect(type(row)).columns})


async def canonical_snapshot():
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SID))
        entities = await db.scalars(
            select(WorldEntity).where(WorldEntity.session_id == SID).order_by(WorldEntity.pk)
        )
        messages = await db.scalars(
            select(ChatMessage).where(ChatMessage.session_id == SID).order_by(ChatMessage.id)
        )
        return {
            "state": columns(state),
            "entities": [columns(row) for row in entities],
            "messages": [columns(row) for row in messages],
            "template": columns(await db.get(AdventureTemplate, state.template_id)),
            "avatar": columns(await db.get(Avatar, state.avatar_id)),
        }


async def fresh_recall(owner):
    async with TestSessionLocal() as db:
        user = await db.get(User, owner)
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SID))
        host = SimpleNamespace(db=db, user=user, state=state)
        recall = await retrieval.prepare_recall(host, "harbour lighthouse", [])
        references = [row for row in recall.documents if row.layer == "world_info"]
        return references, recall_block(host, "narrator"), recall_block(host, "mechanics")


def proposal(passage):
    return {
        "facts": [
            {"id": "f1", "text": QUOTE, "evidence": [{"passage_id": passage["id"], "quote": QUOTE}]}
        ],
        "entries": [
            {
                "id": "e1",
                "title": "Harbour lighthouse",
                "summary": "A coastal landmark.",
                "group_name": "Coastal landmarks",
                "fact_ids": ["f1"],
                "tags": ["#harbour"],
                "relations": [],
                "kind": "world_fact",
            }
        ],
    }


async def review_and_correct(client, owner, source, format):
    review = await client.get(URL + "/entries", params={"view": "review"})
    assert review.status_code == 200, review.text
    assert review.json()["total"] == 1
    entry_id = review.json()["entries"][0]["id"]
    assert UUID(entry_id).version == 5
    detail = await client.get(URL + f"/entries/{entry_id}")
    assert detail.status_code == 200, detail.text
    draft = detail.json()
    fact = draft["facts"][0]
    assert UUID(fact["id"]).version == 5
    assert draft["group_name"] == "Coastal landmarks" and draft["tags"] == ["#harbour"]
    assert draft["audience"] == "narrator_only" and draft["status"] == "draft"
    original = deepcopy(fact)
    evidence = fact["evidence"][0]
    assert evidence["quote"] == QUOTE
    assert evidence["source_hash"] == hashlib.sha256(source.encode("utf-8")).hexdigest()
    if format == "json":
        assert evidence["pointer"] == "/灯台" and evidence["start"] == 2
        assert json.loads(source)["灯台"][evidence["start"] : evidence["end"]] == QUOTE
    else:
        assert evidence["pointer"] is None
        assert source[evidence["start"] : evidence["end"]] == QUOTE

    edit = {
        key: deepcopy(draft[key])
        for key in ("version", "title", "summary", "group_name", "kind", "tags", "relations")
    }
    edit.update(
        audience="restricted", known_by=["NPC_NEW"], facts=[{"id": fact["id"], "text": CORRECTED}]
    )
    saved = await client.put(URL + f"/entries/{entry_id}", json=edit)
    assert saved.status_code == 200, saved.text
    corrected = saved.json()
    assert corrected["edited"] and corrected["facts"][0]["edited"]
    assert corrected["facts"][0]["evidence"] == original["evidence"]
    assert corrected["facts"][0]["original_text"] == original["original_text"] == QUOTE
    assert not (await fresh_recall(owner))[0]

    return corrected, original


async def publish_and_recall(client, owner, source_detail, corrected, indexed):
    entry_id = corrected["id"]
    source_id = source_detail["source"]["id"]
    revision_id = source_detail["revision"]["id"]
    publication = await client.post(
        URL + "/publish",
        json={
            "revision_id": revision_id,
            "source_version": source_detail["source"]["version"],
            "entries": [{"id": entry_id, "version": corrected["version"]}],
        },
    )
    assert publication.status_code == 200, publication.text
    assert publication.json()["published"] == 1
    assert publication.json()["source"]["published_revision"] == 1
    indexed.assert_called_once_with(SID, owner)
    references, narrator, mechanics = await fresh_recall(owner)
    assert len(references) == 1
    reference = references[0]
    assert reference.source_id == "world_info:" + entry_id
    assert reference.provenance == "authored_reference" and not reference.source_message_ids
    assert reference.known_by == ("NPC_NEW",) and not reference.unresolved_known_by
    assert reference.reference_kind == "world_fact" and reference.reference_edited
    assert (
        reference.source_attribution["id"] == source_id
        and reference.source_attribution["revision"] == 1
    )
    assert CORRECTED in narrator and QUOTE not in narrator
    assert CORRECTED not in mechanics and "world_info:" not in mechanics
    assert len(narrator) <= 2500


async def unpublish_and_verify(client, owner, corrected, original, source):
    entry_id = corrected["id"]
    revision_id = corrected["source_revision_id"]
    current = (await client.get(URL + f"/entries/{entry_id}")).json()
    removed = await client.post(
        URL + f"/entries/{entry_id}/unpublish", json={"version": current["version"]}
    )
    assert removed.status_code == 200, removed.text
    assert not removed.json()["is_active"]
    references, narrator, mechanics = await fresh_recall(owner)
    assert not references and CORRECTED not in narrator and CORRECTED not in mechanics
    original_source = await client.get(URL + f"/revisions/{revision_id}/content")
    assert original_source.json()["content"] == source
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoEntry, entry_id)
        revision = await db.get(WorldInfoRevision, revision_id)
        assert row.facts[0]["evidence"] == original["evidence"]
        assert row.facts[0]["original_text"] == QUOTE and row.facts[0]["text"] == CORRECTED
        assert revision.content == source and revision.attempts == 1


def source_material(format):
    sources = {
        "md": ("# Harbour archive\n\n" + QUOTE + "\n", "harbour.md"),
        "json": (json.dumps({"灯台": "🧭 " + QUOTE}, ensure_ascii=False), "harbour.json"),
        "text": (QUOTE + "\n\nA written coastal note. 🧭", "written-entry.md"),
    }
    return sources[format]


@pytest.mark.parametrize("format", ["md", "json", "text"])
async def test_upload_process_review_publish_recall_and_unpublish(
    auth_client, world_info_owner, monkeypatch, format
):
    owner = world_info_owner
    source, filename = source_material(format)
    dispatches = []
    scheduled = Mock()
    indexed = Mock()
    monkeypatch.setattr(world_info.worker, "schedule", scheduled)
    monkeypatch.setattr(world_info_entries, "schedule_index", indexed)

    async def transport(router, kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        passage = next(row for row in payload["passages"] if QUOTE in row["text"])
        dispatches.append((router.model_category, deepcopy(kwargs), passage))
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(proposal(passage))),
                    finish_reason="stop",
                )
            ],
            model_dump=lambda: {},
        )

    monkeypatch.setattr(GameMasterLLM, "_acompletion_with_openrouter_fallback", transport)
    async with TestSessionLocal() as db:
        user = await db.get(User, owner)
        user.llm_settings = {**user.llm_settings, "memory_rag": {"enabled": True}}
        db.add(
            ChatMessage(session_id=SID, role="assistant", content="Lina waits beside the window.")
        )
        await db.commit()
    baseline = await canonical_snapshot()
    assert not (await fresh_recall(owner))[0]

    uploaded = await auth_client.post(
        URL + "/sources",
        files={"file": (filename, source.encode("utf-8"))},
        data={"title": "Harbour reference"},
    )
    assert uploaded.status_code == 201, uploaded.text
    initial = uploaded.json()
    revision_id = initial["revision"]["id"]
    assert initial["revision"]["status"] == "uploaded"
    assert initial["revision"]["attempts"] == 0
    assert initial["source"]["published_revision"] is None
    assert not dispatches
    scheduled.assert_not_called()

    started = await auth_client.post(
        URL + f"/revisions/{revision_id}/process",
        json={"control_version": initial["revision"]["control_version"]},
    )
    assert started.status_code == 200, started.text
    assert started.json()["revision"]["status"] == "queued"
    scheduled.assert_called_once_with(SID, owner)
    await worker._run(SID, owner)
    status = await auth_client.get(URL + f"/revisions/{revision_id}")
    assert status.status_code == 200, status.text
    job = status.json()["revision"]
    assert (job["status"], job["cursor"], job["total_batches"], job["attempts"]) == (
        "review",
        1,
        1,
        1,
    )
    assert job["facts_count"] == job["entries_count"] == 1
    assert job["processing_language"] == "Russian"
    assert len(dispatches) == 1 and dispatches[0][0] == "generator"
    assert "Russian" in dispatches[0][1]["messages"][0]["content"]
    assert not (await fresh_recall(owner))[0]

    corrected, original = await review_and_correct(auth_client, owner, source, format)
    await publish_and_recall(auth_client, owner, status.json(), corrected, indexed)
    assert await canonical_snapshot() == baseline
    await unpublish_and_verify(auth_client, owner, corrected, original, source)
    assert len(dispatches) == 1 and indexed.call_count == 2
    assert await canonical_snapshot() == baseline
