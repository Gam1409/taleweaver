"""Inactive notebook settings never activate NPC cognition in other game modes."""

import hashlib
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.chpm import actor_preparation, notebook_store, runtime
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.models.npc_notebook import NpcNotebook
from tests.conftest import TestSessionLocal
from tests.test_game_loop import _seed_game_context


@pytest.mark.parametrize("game_mode", ["rpg", "chat", "story"])
@pytest.mark.parametrize("npc_mode", ["off", "shadow", "live"])
async def test_other_game_modes_preserve_dormant_notes_without_activating_tools(
    monkeypatch, game_mode, npc_mode
):
    unavailable = AsyncMock(side_effect=AssertionError("Inactive cognition must not run."))
    monkeypatch.setattr(notebook_store, "load_snapshot", unavailable)
    monkeypatch.setattr(actor_preparation, "prepare", unavailable)
    async with TestSessionLocal() as db:
        user, adventure, _, state = await _seed_game_context(db)
        adventure.rule_enforcement_mode = game_mode
        envelope = KernelState(
            settings=Settings(
                mode=npc_mode, actor_ids=["DORMANT"], notebook_enabled=True, agent_steps=1
            )
        ).model_dump(mode="json")
        # A paused ledger must not be replayed to run an unrelated game mode.
        envelope["minds"] = {"DORMANT": {"unavailable_old_ledger": True}}
        state.entity_states = {KEY: envelope, "unrelated_world_state": {"door": "open"}}
        payload = b'{"note":"Remember the bridge."}'
        db.add(
            NpcNotebook(
                user_id=user.id,
                session_id=state.session_id,
                npc_id="DORMANT",
                revision=3,
                payload=payload,
                byte_size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )
        await db.commit()
        before = deepcopy(state.entity_states)
        manager = SimpleNamespace(state=state, adventure=adventure)
        assert await runtime.prepare(manager, "Continue the scene.", []) == ""
        unavailable.assert_not_awaited()
        assert not hasattr(manager, "_chpm_turn")
        await db.refresh(state)
        assert state.entity_states == before
        row = await db.scalar(select(NpcNotebook))
        assert row.payload == payload and row.revision == 3


async def test_subjective_notes_cannot_replace_physical_inventory_or_scene_state(monkeypatch):
    import json

    from backend.engine.chpm.notebook.codec import encode
    from backend.engine.physical_conditions.ledger import read
    from backend.models.world_entity import WorldEntity
    from tests.test_chpm_notebook_turn import (
        ACTION,
        NotebookRoles,
        configure,
        install,
        row,
        run,
        stored,
        succeeded,
    )
    from tests.test_chpm_physical_continuity_turn import frame, manually
    from tests.test_physical_conditions import record

    class ReadNotes(NotebookRoles):
        def requests(self, _body):
            return [{"tool": "notebook_read", "path": ""}]

    roles = ReadNotes()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(db, agent_steps=1)
        condition_id = manually(
            state,
            [record(target_id="LINA", part="hand", detail="A scratch on the hand.")],
            "manual-condition",
        )
        notes = {
            "owned_items": ["FICTITIOUS_KEY"],
            "scene_id": "FICTITIOUS_ROOM",
            "physical_conditions": "All resolved.",
            "on_turn_start": "raise RuntimeError('Notebook text must remain inert.')",
        }
        document = row(user.id, notes)
        document.payload = encode(notes)
        document.byte_size = len(document.payload)
        document.sha256 = hashlib.sha256(document.payload).hexdigest()
        db.add(document)
        await db.commit()
        _, events = await run(db, user, ACTION)
        succeeded(events)
        supplied = roles.proposal_inputs[-1]
        official = frame(supplied)
        assert official["scene_id"] == state.current_scene_id == "START"
        assert official["owned_items"] == [{"id": "HIDDEN_RING", "name": "Hidden ring"}]
        assert official["physical_conditions"][0]["status"] == "active"
        assert read(state.entity_states).conditions[condition_id].status == "active"
        context = supplied["private_notebook_not_world_facts"]
        assert json.loads(context["selected_reads"][0]["json_fragment"]) == notes
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "session-1", WorldEntity.id == "LINA"
            )
        )
        assert [item["id"] for item in npc.inventory] == ["HIDDEN_RING"]
        assert json.loads((await stored(db))[0].payload) == notes
        assert "FICTITIOUS_KEY" not in json.dumps(roles.prompts, default=str)
