"""Verified last-frame observations reach cognition without becoming ongoing facts."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.core.text_evidence import EvidenceSpan
from backend.engine.chpm import continuation, host_scene
from backend.engine.chpm.schema import KernelState
from backend.engine.chpm.state import load
from backend.engine.scene_continuity.ledger import apply
from backend.engine.scene_illustrations.snapshots import capture_scene_snapshot
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import configured, roles_for, run

ACTION = "Lina grips the chair while waiting for the rescue team."
TEXT = ACTION + ' Lina: "Please tell me what happened." A private thought is not public.'


async def seed_frame(db, *, duplicate=False, explicit_span=True, witnesses=None):
    user, state = await configured(db)
    source = ChatMessage(
        session_id=state.session_id,
        role="assistant",
        scene_id="START",
        content=TEXT + (" Later someone recalls: " + ACTION if duplicate else ""),
    )
    db.add(source)
    await db.flush()
    action = {"actor_ids": ["LINA"], "detail": ACTION, "evidence": ACTION}
    if explicit_span:
        action["evidence_span"] = EvidenceSpan(start=0, end=len(ACTION)).model_dump()
    state.entity_states, errors = apply(
        state.entity_states,
        [],
        [action],
        message=source,
        scene_id="START",
        scene_description="A quiet waiting room.",
        session_id=state.session_id,
        minute=10,
        targets={"START", "LINA", "__player__"},
        actor_targets={"LINA", "__player__"},
    )
    assert not errors
    await capture_scene_snapshot(
        db,
        state,
        source,
        {"characters": [{"id": actor} for actor in witnesses or ["LINA"]]},
    )
    state.in_game_time = 11
    await db.commit()
    return user, state, source


async def host(db, state):
    request = ChatMessage(session_id=state.session_id, role="user", content="Can you answer?")
    db.add(request)
    await db.flush()
    actor = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
    manager = SimpleNamespace(
        db=db,
        state=state,
        game_id=state.session_id,
        _vn_player_message_id=request.id,
    )
    turn = SimpleNamespace(input_id=request.id, scene_cues={})
    await host_scene.prepare(manager, turn, [actor])
    return manager, turn, actor


async def test_complete_turn_hands_the_same_scene_to_decision_narrator_and_reviewer(monkeypatch):
    roles = roles_for(monkeypatch)
    reviews = []
    original = roles.simple

    async def observed(*args, **kwargs):
        if kwargs.get("phase") == "validation":
            reviews.append(json.loads(args[1]))
        return await original(*args, **kwargs)

    roles.simple = observed
    async with TestSessionLocal() as db:
        user, state, source = await seed_frame(db, duplicate=True)
        manager, chunks = await run(db, user, "Can you answer?")
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        frame = json.loads(
            roles.proposal_inputs[-1]["psychological_state"]["current_host_observations"][0]["text"]
        )
        moment = frame["last_observed_scene"]
        assert moment["source_message_id"] == source.id
        assert moment["actions"][0]["quote"] == ACTION
        assert moment["actions"][0]["evidence_span"] == {"start": 0, "end": len(ACTION)}
        assert moment["recorded_minute"] == 10
        assert moment["meaning"] == "last_completed_frame_not_ongoing"
        assert "private thought" not in json.dumps(moment)
        assert roles.chpm_calls == ["perception", "proposal", "validation"]
        assert "current_scene_observations" in json.dumps(roles.prompts[-1])
        assert (
            reviews[-1]["contract"]["LINA"]["current_scene_observations"]["last_observed_scene"]
            == moment
        )
        saved = load(manager.state).minds["LINA"]
        assert any(
            source.facts and source.facts.last_observed_scene for source in saved.sources.values()
        )
        assert manager.state.current_scene_id == "START"


@pytest.mark.parametrize(
    "change",
    [
        "edit",
        "revision",
        "incomplete",
        "room",
        "missing_snapshot",
        "new_observer",
        "newer_reply",
        "future_minute",
    ],
)
async def test_unavailable_or_unwitnessed_moments_do_not_enter_the_actor_view(change):
    async with TestSessionLocal() as db:
        _, state, source = await seed_frame(
            db, witnesses=["OTHER"] if change == "new_observer" else None
        )
        if change == "edit":
            source.content += " A changed ending."
        elif change == "revision":
            source.revision_id = "different-revision"
        elif change == "incomplete":
            source.npc_journal = {"status": "incomplete"}
        elif change == "room":
            state.current_scene_id = "FOREST"
        elif change == "missing_snapshot":
            state.entity_states = {
                key: value
                for key, value in state.entity_states.items()
                if key != "__vn_illustrations__"
            }
        elif change == "newer_reply":
            db.add(
                ChatMessage(
                    session_id=state.session_id, role="assistant", content="A later quiet reply."
                )
            )
        elif change == "future_minute":
            state.in_game_time = 9
        await db.flush()
        manager, turn, actor = await host(db, state)
        assert host_scene.capture(manager, actor, {"LINA": "Lina"}).last_observed_scene is None
        assert turn.scene_cues == {}


@pytest.mark.parametrize("explicit_span", [False, True])
async def test_repeated_words_require_the_original_occurrence(explicit_span):
    async with TestSessionLocal() as db:
        _, state, _ = await seed_frame(db, duplicate=True, explicit_span=explicit_span)
        before = deepcopy(state.entity_states)
        manager, _, actor = await host(db, state)
        moment = host_scene.capture(manager, actor, {"LINA": "Lina"}).last_observed_scene
        assert bool(moment) is explicit_span
        assert state.entity_states == before


async def test_a_new_input_never_reuses_the_previous_turn_cache():
    async with TestSessionLocal() as db:
        _, state, _ = await seed_frame(db)
        manager, _, actor = await host(db, state)
        assert host_scene.capture(manager, actor, {"LINA": "Lina"}).last_observed_scene
        manager._vn_player_message_id = "another-input"
        assert host_scene.capture(manager, actor, {"LINA": "Lina"}).last_observed_scene is None


async def test_time_skip_keeps_the_observation_historical_and_available_in_fallback():
    async with TestSessionLocal() as db:
        _, state, _ = await seed_frame(db)
        state.in_game_time += 3 * 24 * 60
        manager, _, actor = await host(db, state)
        identities = continuation.identities(manager, KernelState(), [actor])
        moment = identities["LINA"]["current_host_state"]["last_observed_scene"]
        assert moment["recorded_minute"] == 10
        assert moment["meaning"] == "last_completed_frame_not_ongoing"
