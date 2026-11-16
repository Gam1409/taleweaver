"""Late narrator guidance retains the same scoped identity data as portrait binding."""

import json
from types import SimpleNamespace

import pytest

from backend.core.npc_presentation import public_cues
from backend.engine.npc_presentation.runtime import prepare
from backend.engine.npc_presentation.settings import KEY


@pytest.mark.parametrize(
    ("names", "line", "feeling", "thought"),
    [
        (("Mira", "Owen"), "لم ينته العمل بعد.", "حذر", "أنتظر نتيجة مؤكدة."),
        (("ミラ", "オーウェン"), "作業はまだ終わっていません。", "警戒", "確かな結果を待とう。"),
        (("Мира", "Оуэн"), "Работа ещё не закончена.", "настороженность", "Дождусь проверки."),
    ],
)
def test_final_reminder_keeps_supplied_names_and_only_the_available_cast(
    names, line, feeling, thought
):
    state = SimpleNamespace(
        current_scene_id="HERE",
        entity_states={
            KEY: {"emotion_palette": True, "character_thoughts": True},
            "ABSENT": {"presence": "absent"},
            "HIDDEN": {"is_hidden": True},
        },
    )
    catalog = {"KEEPER": names[0], "TECHNICIAN": names[1]}
    actors = [
        SimpleNamespace(
            id=identifier,
            name=name,
            current_scene_id="HERE",
            entity_type="NPC",
            is_hidden=False,
        )
        for identifier, name in {**catalog, "ABSENT": "Nora", "HIDDEN": "Hidden"}.items()
    ]
    turn = prepare(SimpleNamespace(state=state), actors)

    assert json.loads(turn.prompt.rsplit("NPC cast: ", 1)[1]) == catalog
    assert json.loads(turn.reminder.rsplit("NPC cast: ", 1)[1]) == catalog
    body = f'{names[0]}: "{line}"\n'
    footer = {
        "npcs": [
            {
                "npc_id": "KEEPER",
                "emotion": feeling,
                "intensity": 63,
                "color_rgb": [141, 160, 210],
                "thought": thought,
            }
        ]
    }
    visible = turn.clean(
        body + "<npc-state>" + json.dumps(footer, ensure_ascii=False) + "</npc-state>"
    )
    assert visible == body
    payload = turn.payload(visible)
    assert payload["npcs"]["KEEPER"]["thought"] == thought
    assert public_cues(payload, visible) == payload
    assert public_cues(payload, body + "Changed.") is None
