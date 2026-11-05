"""Session copies keep identity and evidence while rebasing every core reference."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.chpm.core.contracts import Citation, Event, Interpret
from backend.engine.chpm.core.reducer import apply
from backend.engine.chpm.host_sources import reconcile
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.lifecycle import fork, validate
from backend.engine.chpm.schema import KernelState
from backend.engine.chpm.state import KEY, load
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.engine.turn_replay.snapshot import capture, restore
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import chpm_world, portrait_world
from tests.test_chpm_host_state import mind, record, source

__all__ = ["chpm_world", "portrait_world"]


def interpreted():
    observed = record(mind(), source(), minute=1)
    event = Event(
        scope=observed.genesis.scope,
        event_id="interpret",
        sequence=2,
        sim_minute=1,
        payload=Interpret(
            record_id="inference",
            belief_id="intent",
            statement="Plans an inspection",
            about_id="npc",
            domain="work",
            stance="support",
            citations=(Citation(record_id=observed.snapshot.evidence[0].id, quote="inspect"),),
        ),
    )
    snapshot = apply(observed.snapshot, event, expected_revision=1).snapshot
    return Mind(genesis=observed.genesis, snapshot=snapshot, sources=observed.sources)


def test_fork_replays_beliefs_and_changes_roots_without_rewriting_identity():
    original = interpreted()
    raw = {KEY: KernelState(minds={"npc": original}).model_dump(mode="json")}
    backup = deepcopy(raw)
    result = fork(raw, {"m1": "copy1"}, "copied")
    copied = load(SimpleNamespace(entity_states=result)).minds["npc"]
    assert raw == backup
    assert copied.genesis.identity == original.genesis.identity
    assert copied.genesis.scope.world_id == "copied"
    assert {s.message_id for s in copied.sources.values()} == {"copy1"}
    old_belief, new_belief = original.snapshot.beliefs[0], copied.snapshot.beliefs[0]
    assert new_belief.statement == old_belief.statement
    assert new_belief.support_roots != old_belief.support_roots
    assert copied.snapshot.evidence[1].citations[0].record_id == copied.snapshot.evidence[0].id
    with pytest.raises(ValueError, match="another session"):
        validate(raw, "copied")


def test_missing_copy_source_removes_dependent_suffix_not_identity():
    original = record(interpreted(), source("m2"), minute=2)
    result = fork(
        {KEY: KernelState(minds={"npc": original}).model_dump()}, {"m2": "copy2"}, "copied"
    )
    copied = load(SimpleNamespace(entity_states=result)).minds["npc"]
    assert copied.snapshot.cursor == 0 and not copied.sources
    assert copied.genesis.identity == original.genesis.identity
    assert fork({"unrelated": 1}, {}, "copied") == {"unrelated": 1}
    assert fork({KEY: None}, {}, "copied") == {KEY: None}


@pytest.mark.parametrize("operation", ["copy", "export_import"])
async def test_session_lifecycle_rebinds_messages_and_passes_reconciliation(
    auth_client, chpm_world, operation
):
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        state = await db.scalar(select(SessionState).where(SessionState.session_id == session.id))
        message = ChatMessage(
            session_id=session.id, role="assistant", content="I will inspect it", scene_id="room"
        )
        db.add(message)
        await db.flush()
        evidence = source(message.id).model_copy(
            update={
                "revision_id": message.revision_id,
                "content_hash": digest(message.content),
            }
        )
        original = record(mind("NPC_NEW", session.id), evidence, minute=1)
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(minds={"NPC_NEW": original}).model_dump(mode="json"),
        }
        await db.commit()
        if operation == "export_import":
            bundle = await SessionExporter.export_ads(db, session.id)
            copied_id = await SessionImporter.import_ads(db, bundle, session.user_id)
            assert copied_id
    if operation == "copy":
        response = await auth_client.post("/api/adventures/sessions/portrait-session/copy")
        assert response.status_code == 201, response.text
        copied_id = response.json()["game_id"]
    async with TestSessionLocal() as db:
        copied_state = await db.scalar(
            select(SessionState).where(SessionState.session_id == copied_id)
        )
        copied = load(copied_state).minds["NPC_NEW"]
        assert copied.genesis.identity == original.genesis.identity
        assert copied.genesis.scope.world_id == copied_id
        assert {s.message_id for s in copied.sources.values()}.isdisjoint(
            s.message_id for s in original.sources.values()
        )
        manager = SimpleNamespace(db=db, game_id=copied_id)
        assert await reconcile(manager, copied) == copied


async def test_invalid_restore_is_rejected_before_any_live_row_changes(chpm_world):
    async with TestSessionLocal() as db:
        snapshot = await capture(db, "portrait-session")
        corrupt = deepcopy(snapshot)
        corrupt["state"]["entity_states"][KEY] = KernelState(minds={"npc": mind()}).model_dump(
            mode="json"
        )
        with pytest.raises(ValueError, match="another session"):
            await restore(db, "portrait-session", corrupt)
        assert await capture(db, "portrait-session") == snapshot
