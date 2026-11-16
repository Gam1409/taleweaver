"""The reserved correction identifies unassigned facts without copying source text."""

import json
from copy import deepcopy
from types import SimpleNamespace

from backend.engine.world_info.extraction import extract_batch
from tests.test_world_info_extraction import proposal, setup_extraction

__all__ = ["setup_extraction"]


async def test_incomplete_grouping_correction_lists_all_unassigned_fact_ids(setup_extraction):
    router, _, plan = setup_extraction
    first = proposal()
    first["facts"] = [{**deepcopy(first["facts"][0]), "id": f"f{i}"} for i in range(1, 9)]
    first["entries"][0]["fact_ids"] = ["f1", "f2"]
    corrected = deepcopy(first)
    corrected["entries"] = [
        {
            **deepcopy(first["entries"][0]),
            "id": f"e{i}",
            "fact_ids": [f"f{2 * i - 1}", f"f{2 * i}"],
        }
        for i in range(1, 5)
    ]

    async def respond(**kwargs):
        if kwargs["metadata"]["attempt"] == 1:
            return first
        prompt = kwargs["user_prompt"]
        marker = "\nHOST_VALIDATION_FEEDBACK_JSON:\n"
        assert marker in prompt
        feedback = json.loads(prompt.split(marker)[1])
        assert feedback["code"] == "incomplete_fact_grouping"
        assert feedback["unassigned_fact_ids"] == [f"f{i}" for i in range(3, 9)]
        assert "quote" not in feedback and "facts" not in feedback
        return corrected

    router.aexecute_complex_task.side_effect = respond
    entries = await extract_batch(
        SimpleNamespace(default_language="English"),
        "session-test",
        "revision-test",
        plan.source_hash,
        plan.batches[0],
    )

    assert len(entries) == 4 and sum(len(entry.facts) for entry in entries) == 8
    assert router.aexecute_complex_task.await_count == 2
    assert first["entries"][0]["fact_ids"] == ["f1", "f2"]
