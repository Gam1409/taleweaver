"""Private notebooks participate in actual accepted VN turns without public evidence."""

import asyncio
import hashlib
import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.chpm import inference, notebook_store, rendering
from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.schema import Settings
from backend.engine.chpm.state import KEY, load
from backend.models.chat import ChatMessage
from backend.models.npc_notebook import NpcNotebook
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_state import mind
from tests.test_chpm_host_turn import configured, run
from tests.test_chpm_local_failure_turn import LocalFailureRoles, seed_pair
from tests.test_chpm_turn import ChpmRoles
from tests.test_session_portraits import portrait_world
from tests.test_vn_turn_integration import install_roles

__all__ = ["portrait_world"]
NOTE = "PRIVATE_NOTE_SENTINEL"
ACTION = "I ask Lina about the next step."


class NotebookRoles(ChpmRoles):
    def __init__(self, fault=None, *, pages=False):
        super().__init__(reject=fault == "review")
        self.fault, self.pages = fault, pages
        self.lookups, self.turn_ids, self.prompt_sizes = [], [], []
        self.paused = asyncio.Event()

    async def simple(self, system, payload, model, **kwargs):
        phase = kwargs.get("phase")
        self.prompt_sizes.append((phase, len(system) + len(payload)))
        if phase != "agent_lookup":
            return await super().simple(system, payload, model, **kwargs)
        self.chpm_calls.append(phase)
        body = json.loads(payload)
        self.lookups.append((system, body))
        message_id = body["observation"]["message_id"]
        if message_id not in self.turn_ids:
            self.turn_ids.append(message_id)
        if body["previous_lookups"] and self.fault:
            return await self.failed_lookup()
        purpose = f"Private reflection: {NOTE}" if "personal_notebook" in body else "Legacy lookup."
        return json.dumps({"purpose": purpose, "requests": self.requests(body)})

    async def failed_lookup(self):
        if self.fault == "timeout":
            raise TimeoutError("Simulated optional lookup timeout")
        if self.fault == "cancel":
            self.paused.set()
            await asyncio.Event().wait()
        if self.fault == "invalid_plan":
            return '{"requests":'
        return json.dumps({"requests": []})

    def requests(self, body):
        if "personal_notebook" not in body:
            return []
        previous = body["previous_lookups"]
        if self.pages:
            offset = previous[-1]["results"][0]["next_offset"] if previous else 0
            return [{"tool": "notebook_read", "path": "/long", "offset": offset}] * 2
        if not previous and len(self.turn_ids) == 1:
            return [
                {
                    "tool": "notebook_write",
                    "path": "/private",
                    "value_json": json.dumps(NOTE),
                    "expected_revision": body["personal_notebook"]["revision"],
                }
            ]
        return (
            [{"tool": "notebook_read", "path": "/private"}]
            if not previous or len(self.turn_ids) == 1
            else []
        )


def install(monkeypatch, roles):
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)


async def configure(db, **options):
    user, state = await configured(db)
    current = load(state)
    current.settings = Settings(
        mode="live",
        actor_ids=["LINA"],
        failure_policy="strict",
        max_calls_per_turn=8,
        agent_steps=2,
        notebook_enabled=True,
    ).model_copy(update=options)
    state.entity_states = {**state.entity_states, KEY: current.model_dump()}
    await db.commit()
    return user, state


def row(owner_id, value=None):
    payload = json.dumps(value or {"private": NOTE}, separators=(",", ":")).encode()
    return NpcNotebook(
        user_id=owner_id,
        session_id="session-1",
        npc_id="LINA",
        payload=payload,
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        revision=1,
    )


async def stored(db):
    return (
        await db.scalars(select(NpcNotebook).where(NpcNotebook.session_id == "session-1"))
    ).all()


def succeeded(events):
    assert not any(event.startswith("event: error") for event in events)
    assert any(event.startswith("event: final") for event in events)


async def test_silent_note_is_committed_once_and_reloaded_by_a_fresh_turn(monkeypatch):
    roles = NotebookRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db)
        first, events = await run(db, user, ACTION)
        succeeded(events)
        documents = await stored(db)
        assert len(documents) == 1 and json.loads(documents[0].payload) == {"private": NOTE}
        second, events = await run(db, user, "I continue the discussion.")
        succeeded(events)
        assert second is not first and len(roles.turn_ids) == 2
        assert roles.lookups[2][1]["personal_notebook"]["revision"] == 1
        context = roles.proposal_inputs[-1]["private_notebook_not_world_facts"]
        assert context["meaning"] == "self_authored_subjective_notes_not_world_evidence"
        assert any(NOTE in page["json_fragment"] for page in context["selected_reads"])
        saved = load(state)
        assert NOTE not in json.dumps(saved.model_dump())
        assert NOTE not in json.dumps(roles.prompts, default=str)
        assert all(NOTE not in message.content for message in await db.scalars(select(ChatMessage)))
        assert not saved.actors["LINA"].agent_evidence
        assert len(await stored(db)) == 1 and saved.usage.calls == 5


@pytest.mark.parametrize("fault", ["review", "timeout", "invalid_plan", "persist"])
async def test_rejected_or_failed_turn_never_keeps_a_staged_note(monkeypatch, fault):
    roles = NotebookRoles(fault)
    install(monkeypatch, roles)
    if fault == "persist":
        original = notebook_store.persist_workspace

        async def fail_after_write(*args, **kwargs):
            await original(*args, **kwargs)
            raise ChpmError("Simulated accepted-turn storage failure")

        monkeypatch.setattr(notebook_store, "persist_workspace", fail_after_write)
    async with TestSessionLocal() as db:
        user, state = await configure(db)
        if fault == "persist":
            db.add(row(user.id, {"private": "Previous accepted note."}))
            await db.commit()
        before = load(state)
        _, events = await run(db, user, ACTION)
        documents = await stored(db)
        if fault == "persist":
            assert len(documents) == 1 and documents[0].revision == 1
            assert json.loads(documents[0].payload) == {"private": "Previous accepted note."}
        else:
            assert documents == []
        await db.refresh(state)
        if fault == "invalid_plan":
            succeeded(events)
            assert load(state).actors["LINA"].agent_audit[-1]["stop"] == "invalid_plan"
            return
        assert any(event.startswith("event: error") for event in events)
        assert not any(event.startswith("event: chunk") for event in events)
        assert load(state) == before


async def test_cancel_after_staging_a_note_keeps_the_committed_state_unchanged(monkeypatch):
    roles = NotebookRoles("cancel")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db)
        before = load(state)
        task = asyncio.create_task(run(db, user, ACTION))
        await asyncio.wait_for(roles.paused.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await db.refresh(state)
        assert load(state) == before and await stored(db) == []


@pytest.mark.parametrize(
    "options",
    [{"notebook_enabled": False}, {"mode": "off"}, {"mode": "shadow"}, {"agent_steps": 0}],
)
async def test_disabled_paths_do_not_load_notes_or_change_existing_tool_budgets(
    monkeypatch, options
):
    roles = NotebookRoles()
    install(monkeypatch, roles)
    lookup = AsyncMock(side_effect=AssertionError("Disabled notebooks must not load."))
    monkeypatch.setattr(notebook_store, "load_snapshot", lookup)
    async with TestSessionLocal() as db:
        user, state = await configure(db, **options)
        db.add(row(user.id))
        await db.commit()
        _, events = await run(db, user, ACTION)
        succeeded(events)
        lookup.assert_not_awaited()
        assert all(
            "notebook_write" not in system and "personal_notebook" not in body
            for system, body in roles.lookups
        )
        assert all(
            "private_notebook_not_world_facts" not in value for value in roles.proposal_inputs
        )
        assert NOTE not in json.dumps(roles.prompts, default=str)
        documents = await stored(db)
        assert len(documents) == 1 and documents[0].revision == 1
        expected = (
            0
            if options.get("mode") == "off"
            else 2
            if options.get("mode") == "shadow"
            else 3
            if options.get("agent_steps") == 0
            else 4
        )
        assert load(state).usage.calls == expected


@pytest.mark.parametrize("budget", [24000, 8000])
async def test_private_read_pages_respect_the_existing_request_budget(monkeypatch, budget):
    roles = NotebookRoles(pages=True)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db, max_input_chars=budget)
        db.add(row(user.id, {"long": NOTE + '\\"\n' * 20000}))
        await db.commit()
        _, events = await run(db, user, ACTION)
        assert all(size <= budget for _, size in roles.prompt_sizes)
        if budget == 8000:
            assert any(event.startswith("event: error") for event in events)
            assert roles.chpm_calls == ["perception", "agent_lookup"]
            assert (await stored(db))[0].revision == 1
            await db.refresh(state)
            assert not load(state).actors and not load(state).minds
            return
        succeeded(events)
        context = roles.proposal_inputs[-1]["private_notebook_not_world_facts"]
        assert context["omitted_reads"] + len(context["selected_reads"]) == 4
        assert all(
            len(json.dumps(page, ensure_ascii=False, separators=(",", ":"))) <= 1400
            for page in context["selected_reads"]
        )
        assert load(state).usage.calls == 5 and (await stored(db))[0].revision == 1


@pytest.mark.parametrize(
    "actor_id", ["unknown", "ITEM_1", "portrait-avatar", "TEMPLATE_ONLY", "OTHER_NPC"]
)
async def test_notebook_storage_requires_an_actual_npc_in_the_owned_session(
    portrait_world, actor_id
):
    from backend.engine.chpm.notebook import NotebookWorkspace
    from backend.models.game_session import GameSession

    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        db.add_all(
            [
                WorldEntity(
                    id="TEMPLATE_ONLY",
                    template_id="portrait-template",
                    entity_type="NPC",
                    name="Template NPC",
                    description="A template-only notebook target.",
                    current_scene_id="TOWER",
                ),
                WorldEntity(
                    id="OTHER_NPC",
                    session_id="other-session",
                    entity_type="NPC",
                    name="Other NPC",
                    description="An NPC in another session.",
                    current_scene_id="TOWER",
                ),
            ]
        )
        await db.flush()
        actor = mind(actor_id, session.id)
        with pytest.raises(ChpmError, match="unavailable"):
            await notebook_store.load_payload(db, actor, session.user_id)
        workspace = NotebookWorkspace()
        workspace.write("/note", '"draft"', expected_revision=0)
        with pytest.raises(ChpmError, match="unavailable"):
            await notebook_store.persist_workspace(db, actor, workspace, owner_id=session.user_id)
        assert (await db.scalars(select(NpcNotebook))).all() == []


class PairNotebookRoles(LocalFailureRoles):
    async def simple(self, system, payload, model, **kwargs):
        phase, body = kwargs.get("phase"), json.loads(payload)
        if phase == "agent_lookup":
            actor = body["observer_id"]
            await asyncio.sleep(0)
            request = {"tool": "notebook_read", "path": "/private"}
            if not body["previous_lookups"]:
                request = {
                    "tool": "notebook_write",
                    "path": "/private",
                    "value_json": json.dumps(f"OWN_NOTE_{actor}"),
                    "expected_revision": body["personal_notebook"]["revision"],
                }
            return json.dumps({"requests": [request]})
        if phase == "proposal":
            actor = body["actor_id"]
            peer = "MILA" if actor == "LINA" else "LINA"
            assert f"OWN_NOTE_{actor}" in payload and f"OWN_NOTE_{peer}" not in payload
            self.proposal_inputs.append(body)
        return await super().simple(system, payload, model, **kwargs)


@pytest.mark.parametrize("concurrency", [1, 2])
@pytest.mark.parametrize("bad_actor", [None, "MILA"])
async def test_actor_notebooks_stay_private_and_only_successful_decisions_publish_writes(
    monkeypatch, concurrency, bad_actor
):
    roles = PairNotebookRoles()
    roles.bad_actors = {bad_actor} if bad_actor else set()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed_pair(db, concurrency=concurrency)
        current = load(state)
        current.settings = current.settings.model_copy(
            update={"notebook_enabled": True, "agent_steps": 2, "max_calls_per_turn": 11}
        )
        state.entity_states = {**state.entity_states, KEY: current.model_dump()}
        await db.commit()
        _, events = await run(db, user, ACTION)
        succeeded(events)
        documents = {document.npc_id: json.loads(document.payload) for document in await stored(db)}
        expected = {"LINA"} if bad_actor else {"LINA", "MILA"}
        assert set(documents) == expected
        assert all(value == {"private": f"OWN_NOTE_{actor}"} for actor, value in documents.items())
        assert "OWN_NOTE_" not in json.dumps(load(state).model_dump())
        assert "OWN_NOTE_" not in json.dumps(roles.prompts, default=str)
        assert set(load(state).usage.actor_failures) == ({bad_actor} if bad_actor else set())
