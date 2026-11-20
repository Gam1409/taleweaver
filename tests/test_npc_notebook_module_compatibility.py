"""Notebook compatibility at CHPM configuration and source lifecycle boundaries."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.routes.adventures import regeneration
from backend.engine.chpm import (
    continuation_writer,
    control_settings,
    semantic_index,
    semantic_recall,
)
from backend.engine.chpm.host_state import Source, record
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.schema import KernelState
from backend.engine.chpm.state import KEY, load, save
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.memory_rag.scheduling import IdleScheduler
from backend.engine.memory_rag.settings import embedding_signature, read_settings
from backend.engine.memory_rag.store import LanceMemoryStore
from backend.engine.memory_rag.worker import Claim
from backend.models.chat import ChatMessage
from backend.models.memory_rag import MemoryIndexState
from tests.chpm_reference_fixture import evidence_text
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_notebook_turn import (
    ACTION,
    NOTE,
    NotebookRoles,
    configure,
    install,
    row,
    stored,
    succeeded,
)


class CompatibilityRoles(NotebookRoles):
    note = NOTE
    write_next = False

    def __init__(self, fault=None):
        super().__init__(fault)
        self.fallback_inputs = []

    def requests(self, body):
        if self.write_next and not body["previous_lookups"]:
            return [
                {
                    "tool": "notebook_write",
                    "path": "/private",
                    "value_json": json.dumps(self.note),
                    "expected_revision": body["personal_notebook"]["revision"],
                }
            ]
        requests = super().requests(body)
        for request in requests:
            if request["tool"] == "notebook_write":
                request["value_json"] = json.dumps(self.note)
        return requests

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") == "rp_continuation":
            self.fallback_inputs.append((system, payload, kwargs.get("messages")))
            return "Lina considers the next step before continuing the discussion."
        return await super().simple(system, payload, model, **kwargs)


@pytest.mark.parametrize("agent_steps", [1, 2])
@pytest.mark.parametrize("memory_limit", [0, 24])
@pytest.mark.parametrize("failure_policy", ["strict", "continue"])
@pytest.mark.parametrize("semantic_memory", [False, True])
async def test_live_notebook_configuration_boundaries_do_not_depend_on_recall_limits(
    monkeypatch, agent_steps, memory_limit, failure_policy, semantic_memory
):
    roles = CompatibilityRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(
            db,
            agent_steps=agent_steps,
            memory_limit=memory_limit,
            failure_policy=failure_policy,
            semantic_memory=semantic_memory,
        )
        _, events = await run(db, user, ACTION)
        succeeded(events)
        saved = load(state)
        documents = await stored(db)
        assert len(documents) == 1 and json.loads(documents[0].payload) == {"private": NOTE}
        assert saved.usage.calls == 3 + agent_steps
        assert saved.usage.semantic_recall == (
            {"LINA": "lexical_fallback"} if semantic_memory else {}
        )
        context = roles.proposal_inputs[-1]["private_notebook_not_world_facts"]
        assert context["pending_changes"]
        assert bool(context["selected_reads"]) is (agent_steps == 2)
        assert NOTE not in json.dumps(saved.model_dump())
        assert NOTE not in json.dumps(roles.prompts, default=str)
        if memory_limit == 0:
            assert saved.memories.get("LINA", []) == []


@pytest.mark.parametrize("version", range(1, 7))
def test_legacy_kernel_settings_load_and_save_without_enabling_notebooks(version):
    original = KernelState().model_dump(mode="json")
    original["schema_version"] = version
    original["settings"].pop("notebook_enabled")
    original["settings"]["agent_steps"] = 1
    backup = deepcopy(original)
    state = SimpleNamespace(entity_states={KEY: original})
    restored = load(state)
    assert restored.schema_version == 6 and not restored.settings.notebook_enabled
    assert restored.settings.agent_steps == 1 and restored.settings.memory_limit == 12
    assert not control_settings.read(original).notebook_enabled
    save(state, restored, expected_revision=0)
    saved = load(state)
    assert saved.settings == restored.settings and saved.revision == 1
    assert original == backup and "notebook_enabled" not in original["settings"]


async def test_global_continue_fallback_discards_a_staged_note_without_exposing_it(monkeypatch):
    roles = CompatibilityRoles("review")
    install(monkeypatch, roles)
    monkeypatch.setattr(continuation_writer, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db, failure_policy="continue")
        db.add(row(user.id, {"private": "Previous accepted note."}))
        await db.commit()
        _, events = await run(db, user, ACTION)
        succeeded(events)
        saved = load(state)
        assert saved.usage.simplified and saved.usage.fallback_requests == 1
        assert saved.recovery.pending_gap_turns == 1 and not saved.minds
        documents = await stored(db)
        assert len(documents) == 1 and documents[0].revision == 1
        assert json.loads(documents[0].payload) == {"private": "Previous accepted note."}
        assert len(roles.fallback_inputs) == 1
        assert NOTE not in json.dumps(roles.fallback_inputs, default=str)
        assert NOTE not in json.dumps(saved.model_dump())


@pytest.mark.parametrize("reject", [False, True])
async def test_full_turn_retry_uses_current_note_and_preserves_it_if_retry_fails(
    monkeypatch, reject
):
    roles = CompatibilityRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db)
        _, events = await run(db, user, ACTION)
        succeeded(events)
        confirmed = load(state)
        original_reply = confirmed.actors["LINA"].reply_id
        original_note_id = (await stored(db))[0].id
        roles.note = "A newly considered private note."
        roles.write_next = True
        roles.reject = reject
        manager = GameTurnManager(db, "session-1", user)
        events = [
            event
            async for event in manager.process_turn(
                "Ignored retry text.", replay_message_id=original_reply
            )
        ]
        await db.refresh(state)
        documents = await stored(db)
        assert len(documents) == 1 and documents[0].id == original_note_id
        assert roles.lookups[2][1]["personal_notebook"]["revision"] == 1
        if reject:
            assert any(event.startswith("event: error") for event in events)
            assert json.loads(documents[0].payload) == {"private": NOTE}
            assert documents[0].revision == 1 and load(state) == confirmed
            return
        succeeded(events)
        assert json.loads(documents[0].payload) == {"private": roles.note}
        assert documents[0].revision == 2
        assert await db.get(ChatMessage, original_reply) is None
        assert roles.note not in json.dumps(load(state).model_dump())


@pytest.mark.parametrize("change", ["source_edit", "narration_rewrite"])
async def test_changed_story_evidence_retains_the_current_private_note(monkeypatch, change):
    roles = CompatibilityRoles()
    install(monkeypatch, roles)
    rewrite = AsyncMock(return_value="Lina thanks the traveler and continues the discussion.")
    monkeypatch.setattr(regeneration, "generate_narration", rewrite)
    async with TestSessionLocal() as db:
        user, state = await configure(db)
        _, events = await run(db, user, ACTION)
        succeeded(events)
        original_reply = load(state).actors["LINA"].reply_id
        original_hash = digest((await db.get(ChatMessage, original_reply)).content)
        original_note = (await stored(db))[0]
        identity = original_note.id, original_note.payload, original_note.revision
        if change == "source_edit":
            message = await db.get(ChatMessage, original_reply)
            message.content = "Lina considers a revised explanation."
            await db.commit()
            rewrite.assert_not_awaited()
        else:
            await regeneration.regenerate_latest_message(
                "session-1", regeneration.RegenerateRequest(message_id=original_reply), db, user
            )
            rewrite.assert_awaited_once()
            assert load(state).actors == {}
        current = (await stored(db))[0]
        assert (current.id, current.payload, current.revision) == identity
        _, events = await run(db, user, "I ask about the revised discussion.")
        succeeded(events)
        context = roles.proposal_inputs[-1]["private_notebook_not_world_facts"]
        assert any(NOTE in page["json_fragment"] for page in context["selected_reads"])
        assert NOTE not in json.dumps(load(state).model_dump())
        assert all(
            source.message_id != original_reply or source.content_hash != original_hash
            for source in load(state).minds["LINA"].sources.values()
        )


async def test_hybrid_semantic_evidence_and_private_note_remain_distinct_in_a_live_turn(
    monkeypatch, tmp_path
):
    roles = CompatibilityRoles()
    install(monkeypatch, roles)
    vectors = LanceMemoryStore(tmp_path)
    monkeypatch.setattr(semantic_index, "LanceMemoryStore", lambda: vectors)
    monkeypatch.setattr(semantic_recall, "LanceMemoryStore", lambda: vectors)
    monkeypatch.setattr(semantic_index, "scheduler", IdleScheduler(grace_seconds=0))
    embedded = []

    async def embed(_user, texts, **kwargs):
        embedded.append((texts, kwargs))
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(semantic_index, "embed_texts", embed)
    monkeypatch.setattr(semantic_recall, "embed_texts", embed)
    async with TestSessionLocal() as db:
        user, state = await configure(db)
        _, events = await run(db, user, ACTION)
        succeeded(events)
        current = load(state)
        evidence = ChatMessage(
            session_id="session-1",
            role="assistant",
            content="The copper specimen is in locker 7319.",
            scene_id=state.current_scene_id,
        )
        db.add(evidence)
        await db.flush()
        current.minds["LINA"] = record(
            current.minds["LINA"],
            Source(
                message_id=evidence.id,
                revision_id=evidence.revision_id,
                content_hash=digest(evidence.content),
                role="assistant",
                speaker_id="LINA",
                kind="narration",
                text=evidence.content,
            ),
            minute=current.minds["LINA"].snapshot.sim_minute,
        )
        current.settings.semantic_memory = True
        state.entity_states = {**state.entity_states, KEY: current.model_dump()}
        user.llm_settings = {
            **(user.llm_settings or {}),
            "memory_rag": {
                "enabled": True,
                "base_url": "http://localhost:11434",
                "model": "offline-embedding",
            },
        }
        signature = embedding_signature(read_settings(user), 2)
        index = await db.get(MemoryIndexState, "session-1")
        index.signature, index.lease_token = signature, "compatibility-test"
        await db.commit()
        assert await semantic_index.index_batch(
            Claim(
                "session-1",
                user.id,
                index.epoch,
                index.desired_revision,
                "compatibility-test",
                signature,
                False,
            ),
            user,
        )
        _, events = await run(db, user, "Where is the copper specimen?")
        succeeded(events)
        saved = load(state)
        assert saved.usage.semantic_recall == {"LINA": "hybrid"}
        assert saved.usage.calls == 5
        proposal = roles.proposal_inputs[-1]
        assert "retrieved_episode_context" in proposal
        assert any(
            "7319" in evidence_text(item)
            for item in proposal["appraisal_context"]["visible_evidence"]
        )
        assert NOTE in json.dumps(proposal["private_notebook_not_world_facts"])
        assert any("7319" in item.text for item in saved.actors["LINA"].agent_evidence)
        assert NOTE not in json.dumps(saved.model_dump())
        assert all(NOTE not in json.dumps(texts) for texts, _ in embedded)
