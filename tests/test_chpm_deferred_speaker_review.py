"""Exact deferred speech is a known narration violation, not an unavailable review."""

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.chpm import inference, rendering
from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.schema import Verdict
from backend.engine.chpm.state import load
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_chpm_fallback import continuing
from tests.test_chpm_local_failure_turn import LocalFailureRoles, install, play, seed_pair

DEFERRED = "Лина: «Я начну новый разговор.»"


class DeferredSpeakerRoles(LocalFailureRoles):
    def __init__(self, *, repeat):
        super().__init__()
        self.repeat = repeat

    @property
    def story(self):
        return super().story + ("\n" + DEFERRED if self.bad_actors else "")

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") == "repair" and self.repeat:
            return self.story
        return await super().simple(system, payload, model, **kwargs)

    def review(self, supplied):
        result = json.loads(super().review(supplied))
        if "LINA" in supplied["inactive_controlled_actors"]:
            matches = [key for key, text in supplied["passages"].items() if DEFERRED in text]
            if matches:
                result["heard"] = [
                    {"actor_id": "MILA", "speaker_id": "LINA", "passage_id": matches[0]}
                ]
        return json.dumps(result)


@pytest.mark.parametrize("concurrency", [1, 2])
@pytest.mark.parametrize("repeat", [False, True])
async def test_deferred_speech_is_repaired_or_replaced_before_the_reply_is_published(
    monkeypatch, concurrency, repeat
):
    roles = DeferredSpeakerRoles(repeat=repeat)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed_pair(db, concurrency=concurrency)
        host, _ = await play(db, user)
        before = load(host.state).model_copy(deep=True)
        roles.bad_actors = {"LINA"}
        review_count = len(roles.reviews)

        host, _ = await play(db, user, "Продолжим разговор.")

        await db.refresh(state)
        saved = load(state)
        reply = await db.scalar(
            select(ChatMessage)
            .where(ChatMessage.session_id == "session-1", ChatMessage.role == "assistant")
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
        assert DEFERRED not in reply.content
        assert len(roles.reviews) == review_count + 2
        assert saved.usage.repairs == 1
        assert saved.minds["LINA"] == before.minds["LINA"]
        if repeat:
            assert saved.usage.fallback_reason == "review_rejected"
            assert saved.usage.fallback_requests == 1
            assert saved.actors == before.actors and saved.minds == before.minds
        else:
            assert saved.usage.status == "validated" and not saved.usage.simplified
            assert saved.actors["MILA"].reply_id != before.actors["MILA"].reply_id


@pytest.mark.parametrize("invalid", ["quote", "observer"])
async def test_invalid_hearing_metadata_remains_unconfirmed(monkeypatch, invalid):
    host, turn = continuing()
    turn.present_names = {"npc": "Rin", "peer": "Mila"}
    turn.deferred_names = {"peer": "Mila"}
    heard = {"actor_id": "npc", "speaker_id": "peer", "quote": "The bridge is ready."}
    heard["quote" if invalid == "quote" else "actor_id"] = "unavailable"
    verdict = Verdict(
        matches=True,
        evidence=[{"actor_id": "npc", "quote": "Let us discuss the repair."}],
        heard=[heard],
    )
    monkeypatch.setattr(inference, "request", AsyncMock(return_value=verdict))
    repair = AsyncMock(side_effect=AssertionError("No known narration violation"))
    monkeypatch.setattr(rendering, "_repair", repair)
    text = "Let us discuss the repair. The bridge is ready."
    assert (
        await rendering.validate(host, text, completed=True, resolution="", system_prompt="Policy")
        == text
    )
    assert turn.usage.fallback_reason == "review_unavailable"
    repair.assert_not_awaited()


async def test_strict_policy_never_releases_repeated_deferred_speech(monkeypatch):
    host, turn = continuing()
    turn.initial.settings.failure_policy = "strict"
    turn.present_names = {"npc": "Rin", "peer": "Mila"}
    turn.deferred_names = {"peer": "Mila"}
    text = "Let us discuss the repair. The bridge is ready."
    verdict = Verdict(
        matches=True,
        evidence=[{"actor_id": "npc", "quote": "Let us discuss the repair."}],
        heard=[{"actor_id": "npc", "speaker_id": "peer", "quote": "The bridge is ready."}],
    )
    review = AsyncMock(return_value=verdict)
    repair = AsyncMock(return_value=text)
    monkeypatch.setattr(inference, "request", review)
    monkeypatch.setattr(rendering, "_repair", repair)

    with pytest.raises(ChpmError, match="after one repair"):
        await rendering.validate(host, text, completed=True, resolution="", system_prompt="Policy")

    assert repair.await_count == 1 and review.await_count == 2
    assert turn.verdict is None and turn.simplified_text is None
    assert not turn.simplified
