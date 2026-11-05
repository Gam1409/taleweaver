"""The explicit live probe remains bounded and can be verified without a server."""

import pytest

from backend.engine.chpm.evaluation.appraisal_probe import CASES, run
from tests.test_chpm_evaluation import Models


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
