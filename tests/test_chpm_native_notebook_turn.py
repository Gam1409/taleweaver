"""Native notebook calls publish only through the existing reviewed turn transaction."""

import asyncio
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.chpm import notebook_store
from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.notebook import MAX_BYTES
from backend.engine.chpm.state import KEY, load
from backend.models.chat import ChatMessage
from tests.chpm_reference_fixture import tool_turn as reference_turn
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import LocalFailureRoles, seed_pair
from tests.test_chpm_native_notebook_loop import call, turn
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


def initial_payload(messages):
    return json.loads(next(message["content"] for message in messages if message["role"] == "user"))


def tool_results(messages):
    return [json.loads(message["content"]) for message in messages if message["role"] == "tool"]


class NativeRoles(NotebookRoles):
    def __init__(self, fault=None):
        super().__init__(fault)
        self.native_requests, self.native_turn_ids = [], []

    def for_role(self, *args, **kwargs):
        model = super().for_role(*args, **kwargs)
        model.aexecute_tool_turn = self.reference_native
        return model

    async def reference_native(self, messages, tools, model, **kwargs):
        return reference_turn(await self.native(messages, tools, model, **kwargs), messages)

    async def native(self, messages, tools, model, **kwargs):
        body = initial_payload(messages)
        self.native_requests.append((deepcopy(messages), deepcopy(tools), kwargs))
        self.chpm_calls.append(kwargs["phase"])
        message_id = body["observation"]["message_id"]
        if message_id not in self.native_turn_ids:
            self.native_turn_ids.append(message_id)
        previous = tool_results(messages)
        if previous:
            return await self.next_round(body)
        if self.fault == "last_error":
            return turn(call("metadata", "notebook_info", {}))
        if self.fault == "correction":
            return turn(
                call("missing-revision", "notebook_write", {"path": "/private", "value": NOTE})
            )
        if self.fault == "exact_limit":
            return turn(call("root-page", "notebook_read", {"path": "", "limit": 1400}))
        if len(self.native_turn_ids) > 1:
            return turn(call("fresh-read", "notebook_read", {"path": "/private"}))
        return self.write_and_read(body)

    async def next_round(self, body):
        if self.fault == "timeout":
            raise TimeoutError("Simulated native timeout after staging")
        if self.fault == "cancel":
            self.paused.set()
            await asyncio.Event().wait()
        if self.fault == "truncation":
            return turn(call("cutoff", "notebook_read", {}), finish_reason="length")
        if self.fault == "last_error":
            return turn(call("missing-path", "notebook_read", {"path": "/missing"}))
        if self.fault == "correction":
            return self.write_and_read(body)
        return turn()

    @staticmethod
    def write_and_read(body):
        return turn(
            call(
                "private-write",
                "notebook_write",
                {
                    "path": "/private",
                    "value": NOTE,
                    "expected_revision": body["personal_notebook"]["revision"],
                },
            ),
            call("private-read", "notebook_read", {"path": "/private"}),
        )


async def test_native_write_is_committed_once_and_read_back_by_a_fresh_actor_call(monkeypatch):
    roles = NativeRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db)
        first, events = await run(db, user, ACTION)
        succeeded(events)
        assert len(await stored(db)) == 1
        second, events = await run(db, user, "I continue the discussion.")
        succeeded(events)

        documents = await stored(db)
        assert len(documents) == 1 and documents[0].revision == 1
        assert json.loads(documents[0].payload) == {"private": NOTE}
        assert first is not second and len(roles.native_turn_ids) == 2
        assert len(roles.native_requests) == 4 and roles.lookups == []
        assert initial_payload(roles.native_requests[2][0])["personal_notebook"]["revision"] == 1
        context = roles.proposal_inputs[-1]["private_notebook_not_world_facts"]
        assert any(NOTE in item["json_fragment"] for item in context["selected_reads"])
        assert NOTE not in json.dumps(load(state).model_dump())
        assert NOTE not in json.dumps(roles.prompts, default=str)
        assert all(NOTE not in message.content for message in await db.scalars(select(ChatMessage)))
        assert load(state).usage.calls == 5


async def test_a_native_argument_error_can_be_corrected_and_committed_in_two_rounds(monkeypatch):
    roles = NativeRoles("correction")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db)
        _, events = await run(db, user, ACTION)
        succeeded(events)

        assert len(roles.native_requests) == 2 and roles.lookups == []
        previous = tool_results(roles.native_requests[1][0])
        assert previous[0]["status"] != "ok" and "expected_revision" in json.dumps(previous)
        assert json.loads((await stored(db))[0].payload) == {"private": NOTE}
        assert load(state).usage.calls == 5
        context = roles.proposal_inputs[0]["private_notebook_not_world_facts"]
        assert any(NOTE in item["json_fragment"] for item in context["selected_reads"])


async def test_an_exact_limit_freeform_notebook_is_paged_without_entering_the_prompt_whole(
    monkeypatch,
):
    roles = NativeRoles("exact_limit")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db)
        original = row(user.id, NOTE + "x" * (MAX_BYTES - 2 - len(NOTE)))
        db.add(original)
        await db.commit()
        before = original.id, original.sha256, original.byte_size, original.revision
        assert original.byte_size == MAX_BYTES
        _, events = await run(db, user, ACTION)
        succeeded(events)

        document = (await stored(db))[0]
        assert (document.id, document.sha256, document.byte_size, document.revision) == before
        assert len(roles.native_requests) == 2 and load(state).usage.calls == 5
        for messages, tools, _ in roles.native_requests:
            assert (
                len(json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False)) <= 24000
            )
        context = roles.proposal_inputs[0]["private_notebook_not_world_facts"]
        assert context["used_bytes"] == MAX_BYTES and context["remaining_bytes"] == 0
        assert len(context["selected_reads"]) == 1
        page = context["selected_reads"][0]
        assert page["type"] == "string" and page["complete"] is False
        assert NOTE in page["json_fragment"]
        assert len(json.dumps(page, ensure_ascii=False, separators=(",", ":"))) <= 1400


async def test_last_round_tool_error_reaches_the_private_proposal_without_an_extra_request(
    monkeypatch,
):
    roles = NativeRoles("last_error")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db)
        _, events = await run(db, user, ACTION)
        succeeded(events)

        assert len(roles.native_requests) == 2 and roles.lookups == []
        context = roles.proposal_inputs[0]["private_notebook_not_world_facts"]
        last = context["tool_feedback"][-1]
        assert last["tool"] == "notebook_read" and last["status"] == "missing_path"
        assert last["message"] and len(last["message"]) <= 400
        assert context["pending_changes"] is False and await stored(db) == []
        assert load(state).usage.calls == 5


@pytest.mark.parametrize("fault", ["review", "timeout", "persist"])
async def test_native_staged_write_rolls_back_on_review_transport_or_commit_failure(
    monkeypatch, fault
):
    roles = NativeRoles(fault)
    install(monkeypatch, roles)
    if fault == "persist":
        original = notebook_store.persist_workspace

        async def fail_after_write(*args, **kwargs):
            await original(*args, **kwargs)
            raise ChpmError("Simulated native notebook commit failure")

        monkeypatch.setattr(notebook_store, "persist_workspace", fail_after_write)
    async with TestSessionLocal() as db:
        user, state = await configure(db)
        db.add(row(user.id, {"private": "Earlier accepted note."}))
        await db.commit()
        before = load(state)
        _, events = await run(db, user, ACTION)

        assert any(event.startswith("event: error") for event in events)
        assert not any(event.startswith("event: chunk") for event in events)
        await db.refresh(state)
        assert load(state) == before
        document = (await stored(db))[0]
        assert document.revision == 1 and json.loads(document.payload) == {
            "private": "Earlier accepted note."
        }
        assert len(roles.native_requests) == 2 and roles.lookups == []


async def test_cancelled_native_second_round_cannot_publish_the_first_round_write(monkeypatch):
    roles = NativeRoles("cancel")
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
        assert len(roles.native_requests) == 2 and roles.lookups == []


async def test_native_truncation_discards_prior_staging_without_a_replacement_request(monkeypatch):
    roles = NativeRoles("truncation")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db)
        _, events = await run(db, user, ACTION)
        succeeded(events)

        assert len(roles.native_requests) == 2 and roles.lookups == []
        assert await stored(db) == []
        assert load(state).actors["LINA"].agent_audit[-1]["stop"] == "invalid_plan"
        assert (
            roles.proposal_inputs[0]["private_notebook_not_world_facts"]["pending_changes"] is False
        )


@pytest.mark.parametrize(
    "options",
    [{"notebook_enabled": False}, {"mode": "off"}, {"mode": "shadow"}, {"agent_steps": 0}],
)
async def test_native_capability_is_not_called_or_loaded_when_notebook_path_is_disabled(
    monkeypatch, options
):
    roles = NativeRoles()
    install(monkeypatch, roles)
    lookup = AsyncMock(side_effect=AssertionError("Disabled notebooks must not load."))
    monkeypatch.setattr(notebook_store, "load_snapshot", lookup)
    async with TestSessionLocal() as db:
        user, _ = await configure(db, **options)
        db.add(row(user.id))
        await db.commit()
        _, events = await run(db, user, ACTION)
        succeeded(events)

        lookup.assert_not_awaited()
        assert roles.native_requests == []
        assert (await stored(db))[0].revision == 1
        assert all("private_notebook_not_world_facts" not in body for body in roles.proposal_inputs)


class PairNativeRoles(LocalFailureRoles):
    def __init__(self):
        super().__init__()
        self.native_requests = []

    def for_role(self, *args, **kwargs):
        model = super().for_role(*args, **kwargs)
        model.aexecute_tool_turn = self.native
        return model

    async def native(self, messages, tools, model, **kwargs):
        await asyncio.sleep(0)
        body = initial_payload(messages)
        actor = body["observer_id"]
        self.native_requests.append((actor, deepcopy(messages)))
        if tool_results(messages):
            return turn()
        return turn(
            call(
                "own-write",
                "notebook_write",
                {
                    "path": "/private",
                    "value": f"OWN_NATIVE_{actor}",
                    "expected_revision": body["personal_notebook"]["revision"],
                },
            ),
            call("own-read", "notebook_read", {"path": "/private"}),
        )

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") == "proposal":
            actor = json.loads(payload)["actor_id"]
            peer = "MILA" if actor == "LINA" else "LINA"
            assert f"OWN_NATIVE_{actor}" in payload and f"OWN_NATIVE_{peer}" not in payload
        return await super().simple(system, payload, model, **kwargs)


@pytest.mark.parametrize("concurrency", [1, 2])
@pytest.mark.parametrize("bad_actor", [None, "MILA"])
async def test_native_calls_keep_actor_isolation_and_publish_only_accepted_actors(
    monkeypatch, concurrency, bad_actor
):
    roles = PairNativeRoles()
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
        assert set(documents) == ({"LINA"} if bad_actor else {"LINA", "MILA"})
        assert all(
            value == {"private": f"OWN_NATIVE_{actor}"} for actor, value in documents.items()
        )
        for actor, messages in roles.native_requests:
            peer = "MILA" if actor == "LINA" else "LINA"
            assert f"OWN_NATIVE_{peer}" not in json.dumps(messages)
        assert "OWN_NATIVE_" not in json.dumps(load(state).model_dump())
        assert "OWN_NATIVE_" not in json.dumps(roles.prompts, default=str)
        assert set(load(state).usage.actor_failures) == ({bad_actor} if bad_actor else set())
