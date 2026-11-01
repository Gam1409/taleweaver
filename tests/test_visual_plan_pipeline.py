"""Real persisted plan lifecycle through the illustration job API."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.engine.scene_illustrations import plan_cache, plan_preparation
from backend.engine.scene_illustrations.context import require_snapshot
from backend.engine.scene_illustrations.snapshots import remap_illustrations
from backend.engine.scene_illustrations.visual_plan import Audit
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.engine.visual_plan_lifecycle import KEY, reset
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_scene_illustrations import finish, illustration_world
from tests.test_visual_plan import proposal_for

__all__ = ["illustration_world"]


async def enable(**kwargs):
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        write_settings(state, VnSettings(visual_preparation="plan", **kwargs))
        await db.commit()


@pytest.fixture
def plan_calls(monkeypatch):
    async def reply(user, instruction, data, schema, operation):
        if operation == "visual_plan_audit":
            return Audit(status="passed")
        from backend.engine.scene_illustrations.visual_plan import Atom

        return proposal_for(
            [
                Atom.model_validate({k: v for k, v in a.items() if k != "value_hash"})
                for a in data["atoms"]
            ]
        )

    call = AsyncMock(side_effect=reply)
    monkeypatch.setattr(plan_preparation, "_call", call)
    return call


@pytest.mark.asyncio
async def test_two_cold_calls_then_zero_on_rerender(auth_client, illustration_world, plan_calls):
    await enable()
    first = await finish(auth_client)
    assert first["state"] == "succeeded", first
    assert plan_calls.await_count == 2
    second = await finish(auth_client)
    assert second["state"] == "succeeded", second
    assert plan_calls.await_count == 2
    assert illustration_world[0]["prompt"] == illustration_world[1]["prompt"]
    assert illustration_world[1]["provider_options"]["_generation_details"]["visual_plan"][
        "cache_hit"
    ]


@pytest.mark.asyncio
async def test_failed_audit_is_cached_and_warn_is_visible(
    auth_client, illustration_world, plan_calls, monkeypatch
):
    audit = AsyncMock(
        return_value={
            "status": "failed",
            "issues": [{"atom_id": "artifact", "reason": "contradiction"}],
        }
    )
    monkeypatch.setattr(plan_preparation, "audit", audit)
    await enable()
    first = await finish(auth_client)
    assert first["state"] == "failed", first
    assert not illustration_world
    second = await finish(auth_client)
    assert second["state"] == "failed"
    assert plan_calls.await_count == 1
    assert audit.await_count == 1
    await enable(visual_audit_failure="warn")
    third = await finish(auth_client)
    assert third["state"] == "succeeded", third
    assert (
        illustration_world[0]["provider_options"]["_generation_details"]["visual_plan"][
            "semantic_audit"
        ]
        == "failed"
    )


@pytest.mark.asyncio
async def test_audit_off_never_claims_a_pass(auth_client, illustration_world, plan_calls):
    await enable(visual_audit=False)
    result = await finish(auth_client)
    assert result["state"] == "succeeded", result
    assert plan_calls.await_count == 1
    assert (
        illustration_world[0]["provider_options"]["_generation_details"]["visual_plan"][
            "semantic_audit"
        ]
        == "not_run"
    )


@pytest.mark.asyncio
async def test_late_plan_cannot_publish_after_rewind_or_preference_aba(
    auth_client, illustration_world
):
    await enable()
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        message = await db.get(ChatMessage, "moment-reply")
        snapshot = {
            **require_snapshot(state, message),
            "preferences": VnSettings(visual_preparation="plan").model_dump(),
        }
        from backend.models.game_session import GameSession

        owner = (await db.get(GameSession, "moment")).user_id
    identity, key, _ = await plan_cache.begin("moment", "moment-reply", owner, snapshot, "profile")
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        state.entity_states = reset(state.entity_states)
        await db.commit()
    with pytest.raises(HTTPException) as exc:
        await plan_cache.publish("moment", "moment-reply", owner, identity, key, {})
    assert exc.value.status_code == 409
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        original = deepcopy(state.entity_states)
        copied = remap_illustrations(original, {"moment-reply": "copy"})
        assert KEY not in copied
        assert KEY in original


@pytest.mark.asyncio
async def test_explicit_rebuild_replaces_failed_bundle(auth_client, illustration_world, plan_calls):
    from uuid import uuid4

    from backend.api.routes import visual_jobs

    await enable()
    assert (await finish(auth_client))["state"] == "succeeded"
    job_id = str(uuid4())
    response = await auth_client.post(
        "/api/settings/visual-jobs",
        json={
            "id": job_id,
            "operation": "session_illustration",
            "session_id": "moment",
            "payload": {"message_id": "moment-reply", "refresh_plan": True},
        },
    )
    assert response.status_code == 200
    await visual_jobs._jobs[job_id].task
    assert visual_jobs._jobs[job_id].public()["state"] == "succeeded"
    assert plan_calls.await_count == 4
    assert not illustration_world[1]["provider_options"]["_generation_details"]["visual_plan"][
        "cache_hit"
    ]


@pytest.mark.asyncio
async def test_evidence_changed_during_audit_cannot_attach(
    auth_client, illustration_world, plan_calls, monkeypatch
):
    from backend.api.routes.adventures.regeneration_state import refresh_visual_snapshot

    await enable()

    async def rewrite(*args):
        async with TestSessionLocal() as db:
            state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
            message = await db.get(ChatMessage, "moment-reply")
            message.content = "A replacement scene."
            refresh_visual_snapshot(state, message)
            await db.commit()
        return {"status": "passed", "issues": []}

    monkeypatch.setattr(plan_preparation, "audit", rewrite)
    result = await finish(auth_client)
    assert result["state"] == "failed", result
    assert not illustration_world


@pytest.mark.asyncio
async def test_rewind_during_image_generation_discards_late_image(
    auth_client, illustration_world, plan_calls, monkeypatch
):
    from backend.engine.media_engine import MediaEngine
    from backend.engine.scene_illustrations.snapshots import registry_of

    await enable()
    original = MediaEngine.generate_image

    async def generate(**kwargs):
        url = await original(**kwargs)
        async with TestSessionLocal() as db:
            state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
            state.entity_states = reset(state.entity_states)
            await db.commit()
        return url

    monkeypatch.setattr(MediaEngine, "generate_image", generate)
    result = await finish(auth_client)
    assert result["state"] == "failed", result
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        assert not registry_of(state.entity_states)["images"]


@pytest.mark.asyncio
async def test_publication_merges_fresh_state_and_cache_is_immutable(
    auth_client, illustration_world, plan_calls, monkeypatch
):
    await enable()

    async def update_npc(*args):
        async with TestSessionLocal() as db:
            state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
            state.entity_states = {**state.entity_states, "unrelated": {"new": True}}
            await db.commit()
        return {"status": "passed", "issues": []}

    monkeypatch.setattr(plan_preparation, "audit", update_npc)
    assert (await finish(auth_client))["state"] == "succeeded"
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        message = await db.get(ChatMessage, "moment-reply")
        from backend.models.game_session import GameSession

        owner = (await db.get(GameSession, "moment")).user_id
        assert state.entity_states["unrelated"] == {"new": True}
        identity = plan_cache.token(state, message, require_snapshot(state, message))
        key, entry = next(iter(state.entity_states[KEY]["entries"].items()))
    assert (
        await plan_cache.publish(
            "moment", "moment-reply", owner, identity, key, {"replacement": True}
        )
        == entry
    )
