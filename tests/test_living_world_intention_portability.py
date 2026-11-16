"""Dialogue intentions follow copied source IDs without weakening revision/hash fences."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from backend.engine.living_world import dialogue_memory as memory
from backend.engine.living_world.portability import remap_intentions
from backend.engine.living_world.schema import Simulation
from backend.engine.living_world.state import load
from backend.engine.npc_journal.messages import restore_messages
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.engine.session_exporter import SessionExporter
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.living_world_retry_support import retry_world

__all__ = ["retry_world"]
pytestmark = pytest.mark.asyncio
TEXT = "The guide offered to show the archive shelves."


async def seed_intention(world, *, null_revision=False):
    world.db.add(
        ChatMessage(
            session_id=world.session_id,
            role="user",
            content="Show the archive shelves.",
            scene_id="A",
        )
    )
    await world.db.flush()
    source = ChatMessage(
        id="intention-source",
        session_id=world.session_id,
        role="assistant",
        content=TEXT,
        scene_id="A",
        revision_id="intention-revision",
    )
    world.db.add(source)
    await world.db.flush()
    if null_revision:
        source.revision_id = None
        await world.db.flush()
    manager = SimpleNamespace(
        db=world.db,
        state=world.state,
        game_id=world.session_id,
        _dialogue_intention=(
            "GUIDE",
            "A",
            memory.Choice(
                action="INITIATE",
                motive="Offer practical help.",
                intention="Show the archive shelves.",
                next_action="Point out the catalog.",
            ),
        ),
    )
    memory.remember_completed(manager, source, completed=True)
    await world.db.commit()
    assert (await memory.previous_context(manager, load(world.state), "GUIDE"))[
        "source_message_id"
    ] == source.id
    return source, deepcopy(world.state.living_world)


async def duplicate(client, session_id, operation):
    if operation == "copy":
        response = await client.post(f"/api/adventures/sessions/{session_id}/copy")
        assert response.status_code == 201, response.text
    elif operation == "ads":
        exported = await client.get(f"/api/adventures/sessions/{session_id}/export")
        assert exported.status_code == 200, exported.text
        response = await client.post(
            "/api/adventures/sessions/import",
            files={"file": ("archive-session.ads", exported.content, "application/zip")},
        )
        assert response.status_code == 200, response.text
    else:
        async with TestSessionLocal() as db:
            manifest = await SessionExporter.build_session_manifest(db, session_id)
        payload = {
            "version": "1.3",
            "type": "SESSION_BUNDLE",
            "adventure": {
                "title": "Imported archive intentions",
                "rule_enforcement_mode": "vn",
                "original_manifest": {"version": "1.3", "start_scene_id": "A"},
            },
            "game_state": manifest["session_state"],
            "avatar": manifest["avatar"],
            "chat_history": manifest["chat_messages"],
            "scenes": [{**scene, "name": scene["label"]} for scene in manifest["world_scenes"]],
            "exits": manifest["world_exits"],
            "entities": manifest["world_entities"],
            "world_map": manifest["world_map"],
        }
        response = await client.post(
            "/api/adventures/import/session-bundle", json=jsonable_encoder(payload)
        )
        assert response.status_code == 200, response.text
        async with TestSessionLocal() as db:
            return await db.scalar(
                select(GameSession.id).where(
                    GameSession.template_id == response.json()["adventure_id"]
                )
            )
    return response.json()["game_id"]


@pytest.mark.parametrize("operation", ["copy", "ads", "bundle"])
@pytest.mark.parametrize("null_revision", [False, True])
async def test_real_copy_and_ads_keep_verified_intention_on_destination_source(
    retry_world, auth_client, operation, null_revision
):
    world = retry_world
    source, original = await seed_intention(world, null_revision=null_revision)
    identifier, revision = source.id, source.revision_id
    copied_id = await duplicate(auth_client, world.session_id, operation)
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == copied_id))
        copied = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == copied_id, ChatMessage.content == TEXT
            )
        )
        sim = load(state)
        intention = sim.dialogue_intentions["GUIDE"]
        assert copied.id != identifier
        assert intention.source_message_id == copied.id
        assert intention.source_revision_id == copied.revision_id == revision
        assert intention.content_hash == memory.digest(copied.content)
        assert intention.choice.model_dump() == original["dialogue_intentions"]["GUIDE"]["choice"]
        assert sim.timeline != original["timeline"]
        manager = SimpleNamespace(db=db, state=state, game_id=copied_id)
        for _ in range(2):
            context = await memory.previous_context(manager, sim, "GUIDE")
            assert context["source_message_id"] == copied.id
            assert context["proposal_not_fact"]["intention"] == "Show the archive shelves."
            assert "GUIDE" in sim.dialogue_intentions
        original_state = await db.scalar(
            select(SessionState).where(SessionState.session_id == world.session_id)
        )
        assert original_state.living_world == original
        assert (await db.get(ChatMessage, identifier)).revision_id == revision


async def test_restored_explicit_null_revision_differs_from_omitted_legacy_default(retry_world):
    world = retry_world
    identifiers = restore_messages(
        world.db,
        world.session_id,
        [
            {
                "id": "explicit-null",
                "role": "assistant",
                "content": "A null-revision source.",
                "revision_id": None,
            },
            {
                "id": "omitted",
                "role": "assistant",
                "content": "A legacy source without a revision field.",
            },
            {
                "id": "known",
                "role": "assistant",
                "content": "A known-revision source.",
                "revision_id": "known-revision",
            },
        ],
    )
    await world.db.commit()
    async with TestSessionLocal() as db:
        assert (await db.get(ChatMessage, identifiers["explicit-null"])).revision_id is None
        assert (await db.get(ChatMessage, identifiers["omitted"])).revision_id
        assert (await db.get(ChatMessage, identifiers["known"])).revision_id == "known-revision"


async def test_remapping_retains_only_local_counterparts_and_is_independent_and_repeatable():
    simulation = Simulation()
    for actor, source in (("GUIDE", "old"), ("PEER", "missing")):
        simulation.dialogue_intentions[actor] = memory.IntentionMemory(
            source_message_id=source,
            source_revision_id="pinned",
            content_hash="source-hash",
            scene_id="A",
            choice=memory.Choice(
                action="INITIATE", motive="Offer help.", intention="Show the shelves."
            ),
        )
    raw = simulation.model_dump(mode="json")
    original = deepcopy(raw)
    copied = remap_intentions(raw, {"old": "new"})
    assert set(copied["dialogue_intentions"]) == {"GUIDE"}
    kept = copied["dialogue_intentions"]["GUIDE"]
    assert kept == {**original["dialogue_intentions"]["GUIDE"], "source_message_id": "new"}
    assert remap_intentions(copied, {"old": "new"}) == copied
    kept["choice"]["motive"] = "A destination-only change."
    assert raw == original
    assert remap_intentions(None, {}) is None
    assert remap_intentions(original, {})["dialogue_intentions"] == {}


@pytest.mark.parametrize("change", ["revision", "hash", "role", "foreign", "scene"])
async def test_remapped_intention_keeps_existing_source_fences(retry_world, auth_client, change):
    world = retry_world
    source, _original = await seed_intention(world)
    copied_id = await duplicate(auth_client, world.session_id, "copy")
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == copied_id))
        sim = load(state)
        intention = sim.dialogue_intentions["GUIDE"]
        copied = await db.get(ChatMessage, intention.source_message_id)
        if change == "revision":
            intention.source_revision_id = "another-revision"
        if change == "hash":
            intention.content_hash = memory.digest("A rewritten source.")
        if change == "role":
            copied.role = "user"
        if change == "foreign":
            intention.source_message_id = source.id
        if change == "scene":
            state.current_scene_id = "B"
        context = await memory.previous_context(
            SimpleNamespace(db=db, state=state, game_id=copied_id), sim, "GUIDE"
        )
        assert context == {}


@pytest.mark.parametrize("operation", ["copy", "ads", "bundle"])
async def test_destination_regeneration_retracts_only_destination_intention(
    retry_world, auth_client, monkeypatch, operation
):
    from backend.api.routes.adventures import regeneration

    world = retry_world
    _source, original = await seed_intention(world)
    copied_id = await duplicate(auth_client, world.session_id, operation)
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == copied_id))
        source_id = load(state).dialogue_intentions["GUIDE"].source_message_id
    llm = MagicMock(model="fixture-model")
    llm.aexecute_simple_task = AsyncMock(return_value="The guide described a different shelf.")
    monkeypatch.setattr(regeneration.GameMasterLLM, "for_role", lambda *args, **kwargs: llm)
    monkeypatch.setattr(regeneration, "schedule", MagicMock())
    monkeypatch.setattr(regeneration, "queue_refresh", MagicMock())
    response = await auth_client.post(
        f"/api/adventures/{copied_id}/chat/regenerate", json={"message_id": source_id}
    )
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == copied_id))
        assert load(state).dialogue_intentions == {}
        source_state = await db.scalar(
            select(SessionState).where(SessionState.session_id == world.session_id)
        )
        assert source_state.living_world == original
    llm.aexecute_simple_task.assert_awaited_once()


async def test_checkpoint_rewind_keeps_stable_source_ids_and_forks_timeline(retry_world):
    world = retry_world
    source, original = await seed_intention(world)
    checkpoint = await SessionCheckpointService.create_checkpoint(
        world.db, world.session_id, "MANUAL"
    )
    await world.db.commit()
    changed = load(world.state)
    changed.dialogue_intentions = {}
    from backend.engine.living_world.state import save

    save(world.state, changed)
    await world.db.commit()
    await SessionCheckpointService.restore_checkpoint(world.db, world.session_id, checkpoint.id)
    await world.db.commit()
    await world.db.refresh(world.state)
    restored = load(world.state)
    assert restored.timeline != original["timeline"]
    assert restored.dialogue_intentions["GUIDE"].source_message_id == source.id
    context = await memory.previous_context(
        SimpleNamespace(db=world.db, state=world.state, game_id=world.session_id), restored, "GUIDE"
    )
    assert context["source_message_id"] == source.id
