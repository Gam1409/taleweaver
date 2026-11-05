"""Mock model checks for opt-out, isolation, budgets and publication barriers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import context, inference, rendering, runtime
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import KernelState, Settings, SpokenEvidence, Usage, Verdict
from backend.engine.chpm.state import KEY, load
from backend.engine.turn_replay import stream
from tests.test_chpm_kernel import decision, observation, proposal


def manager(mode="live"):
    value = KernelState(settings=Settings(mode=mode, actor_ids=["npc"]))
    host = SimpleNamespace(
        game_id="session",
        user=SimpleNamespace(),
        state=SimpleNamespace(
            entity_states={KEY: value.model_dump()}, current_scene_id="room", in_game_time=5
        ),
        adventure=SimpleNamespace(rule_enforcement_mode="vn"),
        _vn_player_message_id="input",
        _turn_replay_recorded=True,
    )
    actor = SimpleNamespace(
        id="npc",
        entity_type="NPC",
        name="Rin",
        current_scene_id="room",
        is_hidden=False,
        goal="Repair the bridge",
        character="Engineer",
        metadata_json={},
    )
    return host, actor


async def test_disabled_path_never_calls_model(monkeypatch):
    host, actor = manager("off")
    mocked = AsyncMock(side_effect=AssertionError("Disabled means no requests"))
    monkeypatch.setattr(inference, "request", mocked)
    assert await runtime.prepare(host, "Hello", [actor]) == ""
    assert not runtime.buffered(host)
    assert not hasattr(host, "_chpm_turn")
    mocked.assert_not_called()


@pytest.mark.parametrize("mode", ["shadow", "live"])
async def test_preparation_is_once_and_shadow_does_not_direct_narration(monkeypatch, mode):
    host, actor = manager(mode)
    monkeypatch.setattr(context, "observation", AsyncMock(return_value=observation()))
    monkeypatch.setattr(context, "available", lambda *_: True)
    monkeypatch.setattr(
        context, "actor_context", AsyncMock(return_value={"authored_goal": "Repair the bridge"})
    )
    monkeypatch.setattr(runtime, "release_for_model", AsyncMock())
    mocked = AsyncMock(return_value=proposal())
    monkeypatch.setattr(inference, "request", mocked)
    result = await runtime.prepare(host, "Hello", [actor])
    assert bool(result) == (mode == "live")
    assert runtime.buffered(host) == (mode == "live")
    assert await runtime.prepare(host, "Hello", [actor]) == result
    assert mocked.await_count == 1
    assert load(host.state).actors == {}  # No early state mutation.


async def test_private_context_excludes_journal_and_other_actors():
    host, actor = manager()
    host.state.entity_states["other"] = {"secret": "Hidden betrayal"}
    actor.metadata_json = {"npc_journal": {"entries": [{"text": "Secret known to player"}]}}
    supplied = await context.actor_context(host, actor, None)
    assert "Hidden betrayal" not in str(supplied)
    assert "Secret known to player" not in str(supplied)
    assert supplied["authored_goal"] == "Repair the bridge"


def prepared():
    host, _ = manager()
    host._chpm_turn = runtime.Turn(load(host.state), "input", decisions={"npc": decision()})
    return host


def accepted():
    return Verdict(
        matches=True, evidence=[SpokenEvidence(actor_id="npc", quote="Let us discuss the repair.")]
    )


async def test_matching_reply_commits_source_and_own_speech(monkeypatch):
    host = prepared()
    monkeypatch.setattr(inference, "request", AsyncMock(return_value=accepted()))
    text = "Rin: Let us discuss the repair."
    assert (
        await rendering.validate(
            host, text, completed=True, resolution="", system_prompt="Original policy"
        )
        == text
    )
    reply = SimpleNamespace(id="reply", revision_id="v1", content=text)
    runtime.finish(host, reply, completed=True)
    saved = load(host.state)
    assert saved.actors["npc"].reply_id == "reply"
    assert saved.actors["npc"].spoken_evidence == "Let us discuss the repair."
    assert saved.usage.status == "validated"


async def test_one_repair_only_and_no_unvalidated_commit(monkeypatch):
    host = prepared()
    rejected = Verdict(matches=False, issues=["Added an unrelated promise"])
    review = AsyncMock(return_value=rejected)
    repair = AsyncMock(return_value="Still wrong")
    monkeypatch.setattr(inference, "request", review)
    monkeypatch.setattr(rendering, "_repair", repair)
    with pytest.raises(ChpmError, match="after one repair"):
        await rendering.validate(
            host, "Wrong", completed=True, resolution="", system_prompt="Policy"
        )
    assert review.await_count == 2
    assert repair.await_count == 1
    with pytest.raises(ChpmError, match="without successful validation"):
        runtime.finish(host, SimpleNamespace(), completed=True)
    assert load(host.state).actors == {}


@pytest.mark.parametrize("issue", ["incomplete", "fabricated", "missing-actor"])
async def test_rejects_missing_or_fabricated_validation(monkeypatch, issue):
    host = prepared()
    verdict = accepted()
    if issue == "fabricated":
        verdict.evidence[0].quote = "Not in the text"
    if issue == "missing-actor":
        verdict.evidence = []
    monkeypatch.setattr(inference, "request", AsyncMock(return_value=verdict))
    with pytest.raises(ChpmError):
        await rendering.validate(
            host,
            "Let us discuss the repair.",
            completed=issue != "incomplete",
            resolution="",
            system_prompt="Policy",
        )


def test_request_limits_fail_before_another_model_call():
    settings = Settings(max_calls_per_turn=1)
    usage = Usage()
    inference.reserve(settings, usage, 100)
    with pytest.raises(ChpmError, match="budget exhausted"):
        inference.reserve(settings, usage, 100)
    assert usage.calls == 1
    with pytest.raises(ChpmError, match="size limit"):
        inference.reserve(Settings(), Usage(), 50000)


@pytest.mark.parametrize("succeeds", [True, False])
async def test_publication_waits_for_successful_final_boundary(monkeypatch, succeeds):
    host = SimpleNamespace(_chpm_publish_after_commit=True)

    async def events(*_args):
        host._chpm_publish_after_commit = True
        yield 'event: chunk\ndata: {"content":"A checked answer"}\n\n'
        yield "event: status\ndata: {}\n\n"
        yield "event: final\ndata: {}\n\n" if succeeds else "event: error\ndata: {}\n\n"

    monkeypatch.setattr(stream, "_run", events)
    output = [item async for item in stream.run(host, "", False, None, None, None)]
    assert output[0].startswith("event: status")
    assert any(item.startswith("event: chunk") for item in output) == succeeds
    if succeeds:
        assert output[-2].startswith("event: chunk")
        assert output[-1].startswith("event: final")
