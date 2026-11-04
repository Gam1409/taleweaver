"""Turn focus preserves inspection and arrival exceptions without mandatory scenery."""

import pytest

from backend.api.routes.adventures.turn_prompt_layout import build_narration_turn_block
from backend.engine.narration_focus import narration_focus


@pytest.mark.parametrize(
    ("changed", "inspection", "expected"),
    [
        (False, False, "CONTINUING SCENE"),
        (True, False, "SCENE ARRIVAL"),
        (False, True, "INSPECTION REQUEST"),
        (True, True, "INSPECTION REQUEST"),
    ],
)
def test_turn_focus_reaches_narration_without_changing_authoritative_outcome(
    changed, inspection, expected
):
    focus = narration_focus(scene_changed=changed, inspection_requested=inspection)
    prompt = build_narration_turn_block(
        "Room: library. Door: closed.",
        "The librarian replies.",
        '{"moved": false}',
        [],
        reminders=(focus,),
    )
    assert expected in prompt
    assert "Room: library. Door: closed." in prompt
    assert 'TECHNICAL OUTCOME TO NARRATE: {"moved": false}' in prompt
    assert "no fixed length or mandatory narrator paragraph" in prompt
    if expected == "CONTINUING SCENE":
        assert "description in any language" in prompt
        assert "Do not invent an environmental change" in prompt
    else:
        assert "Omit unchanged surroundings" not in prompt
