"""Accepted chat inputs degrade optional analysis without truncating the request."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.routes.adventures.schemas import ChatRequest
from backend.engine.chpm import capacity, causal_memory, context, continuation, runtime
from backend.engine.chpm.errors import ChpmError, RecoverableChpmError
from backend.engine.chpm.perception_fragments import index
from backend.engine.chpm.state import KEY, load
from tests.test_chpm_runtime import manager


def install_host(monkeypatch, text, *, policy="continue", source_patch=None):
    assert ChatRequest(content=text).content == text
    host, actor = manager()
    state = load(host.state)
    state.settings.failure_policy = policy
    host.state.entity_states = {KEY: state.model_dump()}
    host.db = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                **{
                    "id": "input",
                    "session_id": "session",
                    "role": "user",
                    "content": text,
                    "created_at": datetime.now(timezone.utc),
                    "revision_id": "revision",
                    "scene_id": "room",
                    **(source_patch or {}),
                }
            )
        )
    )
    monkeypatch.setattr(context, "available", lambda *_: True)
    monkeypatch.setattr(continuation, "recalled_identities", AsyncMock(return_value={}))
    monkeypatch.setattr(causal_memory, "prepare", AsyncMock())
    monkeypatch.setattr(capacity, "admit", AsyncMock())
    monkeypatch.setattr(runtime, "release_for_model", AsyncMock())
    return host, actor


@pytest.mark.parametrize("policy", ["continue", "strict"])
@pytest.mark.parametrize(
    "text", ["x" * 6001, "A sentence. " * 33], ids=["6001-characters", "33-fragments"]
)
async def test_observation_limits_honor_the_selected_failure_policy(monkeypatch, text, policy):
    host, actor = install_host(monkeypatch, text, policy=policy)
    if policy == "strict":
        with pytest.raises(ChpmError, match="CHPM could not prepare this turn"):
            await runtime.prepare(host, text, [actor])
        assert not host._chpm_turn.simplified
    else:
        await runtime.prepare(host, text, [actor])
        assert host._chpm_turn.simplified
    assert host._chpm_turn.player_request == text
    assert host._chpm_turn.usage.calls == 0
    assert load(host.state).actors == {}


@pytest.mark.parametrize("source_patch", [{"session_id": "another-session"}, {"role": "assistant"}])
async def test_invalid_host_sources_still_stop_keep_playing(monkeypatch, source_patch):
    host, actor = install_host(monkeypatch, "Wait.", source_patch=source_patch)
    with pytest.raises(ChpmError, match="saved player input") as failure:
        await runtime.prepare(host, "Wait.", [actor])
    assert not isinstance(failure.value, RecoverableChpmError)
    assert not host._chpm_turn.simplified
    assert load(host.state).actors == {}


@pytest.mark.parametrize("text", ["x" * 6000, "A sentence. " * 32, " " + "x" * 6000 + " "])
async def test_exact_observation_boundaries_keep_the_complete_input(monkeypatch, text):
    host, _actor = install_host(monkeypatch, text)
    observed = await context.observation(host, text)
    # Observation's established contract normalizes only edge whitespace.
    assert observed.player_request == text.strip()
    assert host.db.get.return_value.content == text
    assert "".join("".join(index(text).values()).split()) == "".join(text.split())
