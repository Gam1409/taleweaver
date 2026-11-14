"""The model receives the same batch capacity enforced by its tool executor."""

import json

from tests.test_chpm_native_notebook_loop import NativeModel, investigate, turn


async def test_native_tool_batch_capacity_is_supplied_before_the_first_call():
    model = NativeModel([turn()])
    _, _, usage = await investigate(model)

    payload = json.loads(model.requests[0][0][1]["content"])
    assert payload["max_tool_calls_per_round"] == 2
    assert payload["remaining_rounds"] == 2
    assert usage.calls == 1
