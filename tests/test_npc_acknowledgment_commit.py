"""Consumed feedback stays source-valid through the final transaction, without early commits."""

from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select

from backend.engine.chpm import commit_sources, notebook_store, recovery_queue, reports
from backend.engine.chpm.errors import StaleControlError
from backend.engine.chpm.state import KEY, load
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.ledger import read
from backend.models.chat import ChatMessage
from backend.models.npc_notebook import NpcNotebook
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_chpm_action_turn import STATE, ActionRoles
from tests.test_chpm_host_turn import run
from tests.test_chpm_notebook_turn import ACTION, install, stored
from tests.test_chpm_observable_turn import prepare
from tests.test_npc_acknowledgment_freshness import two_consumed_acknowledgments
from tests.test_npc_action_empty_turn import EmptyPlanRoles


@pytest.mark.parametrize("fault", ["edit", "delete"])
async def test_postreview_source_change_rolls_back_actual_published_actions(monkeypatch, fault):
    first_roles = EmptyPlanRoles()
    install(monkeypatch, first_roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", "json", False)
        kernel = load(state)
        kernel.settings.action_tools = True
        kernel.settings.max_input_chars = 64000
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
        first, events = await run(db, user, ACTION)
        assert any(event.startswith("event: final") for event in events), "".join(events)
        previous = load(first.state)
        source_id = previous.actors["LINA"].reply_id
        before_conditions = read(state.entity_states).model_dump()
        roles = ActionRoles()
        install(monkeypatch, roles)
        original = roles.structured
        observed_effects = []

        async def changed(*args, **kwargs):
            result = await original(*args, **kwargs)
            schema = kwargs.get("response_model") or args[2]
            if issubclass(schema, ItemExtraction):
                observed_effects.extend(
                    row.detail for row in read(state.entity_states).conditions.values()
                )
                if fault == "delete":
                    await db.execute(delete(ChatMessage).where(ChatMessage.id == source_id))
                else:
                    row = await db.scalar(select(ChatMessage).where(ChatMessage.id == source_id))
                    row.content = "The consumed source changed during extraction."
                await db.flush()
            return result

        monkeypatch.setattr(roles, "structured", changed)
        _, events = await run(db, user, "I continue the discussion.")

        assert (
            roles.proposal_inputs[-1]["previous_action_results_not_current_state"][
                "source_reply_id"
            ]
            == source_id
        )
        assert STATE in observed_effects  # Real publication preceded the late source failure.
        assert any(event.startswith("event: error") for event in events), "".join(events)
        assert not any(event.startswith("event: final") for event in events)
        await db.refresh(state)
        assert load(state) == previous
        assert read(state.entity_states).model_dump() == before_conditions


@pytest.mark.parametrize("changed", [False, True])
async def test_final_ack_check_follows_pending_writes_and_never_commits_them(monkeypatch, changed):
    async with TestSessionLocal() as db:
        manager, old_reply, _, current = await two_consumed_acknowledgments(db)
        current.initial.settings.mode = "live"
        current.verdict = SimpleNamespace(matches=True)
        current.minds["LINA"] = SimpleNamespace()
        current.notebook_drafts["LINA"] = SimpleNamespace(
            committable=True, workspace=SimpleNamespace(changed=True)
        )
        manager.user = await db.scalar(select(User))
        monkeypatch.setattr(reports, "validate_commit", AsyncMock())
        monkeypatch.setattr(recovery_queue, "commit", AsyncMock())

        async def pending_write(_db, _mind, _workspace, *, owner_id):
            db.add(
                NpcNotebook(
                    user_id=owner_id,
                    session_id=manager.game_id,
                    npc_id="LINA",
                    payload=b"{}",
                    byte_size=2,
                    sha256=sha256(b"{}").hexdigest(),
                    revision=1,
                )
            )
            if changed:
                old_reply.content = "The source changed in the last pending write."
            await db.flush()

        monkeypatch.setattr(notebook_store, "persist_workspace", pending_write)
        commit = AsyncMock(wraps=db.commit)
        monkeypatch.setattr(db, "commit", commit)
        if changed:
            with pytest.raises(StaleControlError, match="acknowledgment source changed"):
                await commit_sources.prepare(manager, current)
        else:
            await commit_sources.prepare(manager, current)
        commit.assert_not_called()
        assert len(await stored(db)) == 1
        await db.rollback()
    async with TestSessionLocal() as db:
        assert await stored(db) == []
