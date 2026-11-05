"""The explicit live probe remains bounded and can be verified without a server."""

from types import SimpleNamespace

import pytest

from backend.engine.chpm.evaluation.appraisal_probe import CASES, _step, run
from backend.engine.chpm.schema import Decision, Settings
from tests.test_chpm_evaluation import Models
from tests.test_chpm_host_state import mind


async def test_bounded_probe_exercises_both_roles_and_saves_all_results(tmp_path):
    models = Models()
    results = await run(models, tmp_path / "probe")
    assert len(results) == len(CASES) == 5
    assert all(result["status"] == "ok" for result in results)
    assert sum(len(result["calls"]) for result in results) == 7
    assert all(result["identity_unchanged"] for result in results)
    assert [call["phase"] for call in results[-1]["calls"]] == [
        "proposal",
        "narration",
        "validation",
    ]
    assert len(list((tmp_path / "probe").glob("*.json"))) == 5
    with pytest.raises(FileExistsError):
        await run(models, tmp_path / "probe")


async def test_failed_probe_keeps_accepted_state_and_does_not_render(tmp_path):
    results = await run(Models(broken="proposal"), tmp_path / "failed")
    assert all(result["status"] == "failed" for result in results)
    assert all(result["before"] == result["after"] for result in results)
    assert all(len(result["calls"]) == 1 for result in results)


async def test_two_reviewed_turns_retain_distinct_reply_sources():
    actor = SimpleNamespace(
        id="npc", name="Engineer", character="Independent engineer", goal="Keep bridges safe"
    )
    value = mind(session="appraisal-probe")
    previous = None
    for number in (1, 2):
        result, value = await _step(
            Models(),
            actor,
            Settings(mode="live", actor_ids=["npc"]),
            value,
            number,
            "Let us inspect it.",
            10,
            render=True,
            previous=previous,
        )
        assert result["status"] == "ok", result["error"]
        previous = Decision.model_validate(result["decision"])
        assert previous.status == "delivered"
        assert (previous.previous_intention is not None) == (number == 2)
        assert [call["phase"] for call in result["calls"]] == [
            "proposal",
            "narration",
            "validation",
        ]
    replies = {source.message_id for source in value.sources.values() if source.role == "assistant"}
    assert replies == {"reply-input-1", "reply-input-2"}
