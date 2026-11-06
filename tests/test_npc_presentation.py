"""Optional portrait data cannot leak into story text or invent canonical state."""

import json
from types import SimpleNamespace

import pytest

from backend.core.npc_presentation import PortraitPreferences, public_cues
from backend.engine.npc_presentation.runtime import PresentationTurn, clean_candidate, prepare
from backend.engine.npc_presentation.settings import KEY, PreferencesConflictError, effective, read
from backend.engine.npc_presentation.stream import MAX_FOOTER, FooterStream, split
from backend.models.chat import ChatMessage

BODY = "Рин отвечает: «Я справлюсь».\n"
ENTRY = {"npc_id": "RIN", "emotion": "fear", "intensity": 75, "thought": "Нужно собраться."}


def response(entries=None, body=BODY):
    return (
        body
        + "<npc-state>"
        + json.dumps({"npcs": entries or [ENTRY]}, ensure_ascii=False)
        + "</npc-state>"
    )


def turn(**preferences):
    return PresentationTurn(PortraitPreferences(**preferences), {"RIN": "Rin"})


@pytest.mark.parametrize("cut", range(len(response()) + 1))
def test_every_stream_boundary_hides_footer_and_preserves_unicode(cut):
    raw = response()
    active = turn(emotion_palette=True, character_thoughts=True)
    visible = active.feed(raw[:cut]) + active.feed(raw[cut:]) + active.finish()
    assert visible == BODY
    assert active.output_chars == len(raw)
    assert active.payload(visible)["npcs"]["RIN"] == {
        key: value for key, value in ENTRY.items() if key != "npc_id"
    }


def test_character_stream_and_incomplete_or_invalid_footer_are_nonfatal():
    active = turn(emotion_palette=True)
    visible = "".join(active.feed(char) for char in response()) + active.finish()
    assert visible == BODY
    for suffix in (
        '<npc-state>{"npcs":',
        "<npc-state>oops</npc-state>",
        "<npc-st",
        "<NPC-STATE>{}</NPC-STATE>",
    ):
        active = turn(emotion_palette=True)
        assert active.clean(BODY + suffix) == BODY
        assert active.payload(BODY) is None
    assert split("Use x < y and <n")[0] == "Use x < y and <n"
    assert split("Story<npc-state>" + "x" * (MAX_FOOTER + 1))[0] == "Story"


def test_off_path_has_no_prompt_and_does_not_touch_model_output():
    active = turn()
    assert active.prompt == ""
    assert active.feed(response()) + active.finish() == response()
    assert active.clean(response()) == response()
    assert active.payload(response()) is None


@pytest.mark.parametrize(
    "flags,expected",
    [
        ({"emotion_palette": True}, {"emotion": "fear", "intensity": 75}),
        ({"character_thoughts": True}, {"thought": "Нужно собраться."}),
    ],
)
def test_opt_ins_are_independent(flags, expected):
    active = turn(**flags)
    assert active.clean(response()) == BODY
    assert active.payload(BODY)["npcs"]["RIN"] == expected


@pytest.mark.parametrize(
    "patch",
    [
        {"npc_id": "PLAYER"},
        {"npc_id": ["RIN"]},
        {"emotion": "adoration"},
        {"intensity": True},
        {"intensity": 101},
        {"intensity": "75"},
        {"intensity": -1},
    ],
)
def test_invalid_or_out_of_scope_assessments_do_not_create_glow(patch):
    active = turn(emotion_palette=True)
    assert active.clean(response([{**ENTRY, **patch}])) == BODY
    assert active.payload(BODY) is None


def test_invalid_emotion_does_not_discard_independent_valid_thought():
    active = turn(emotion_palette=True, character_thoughts=True)
    active.clean(response([{**ENTRY, "intensity": "high"}]))
    assert active.payload(BODY)["npcs"]["RIN"] == {"thought": ENTRY["thought"]}
    active = turn(character_thoughts=True)
    active.clean(response([{**ENTRY, "thought": "x" * 161}]))
    assert active.payload(BODY) is None


def test_repaired_prose_does_not_inherit_rejected_candidate_state():
    active = turn(emotion_palette=True)
    manager = SimpleNamespace(_portrait_presentation=active)
    active.clean(response())
    assert active.payload("Different approved reply") is None
    fixed = clean_candidate(
        manager, response([{**ENTRY, "emotion": "calm", "intensity": 30}], "Approved")
    )
    assert fixed == "Approved"
    assert active.payload(fixed)["npcs"]["RIN"]["emotion"] == "calm"
    assert active.payload(BODY)["npcs"]["RIN"]["emotion"] == "fear"


def test_settings_are_strict_but_old_sessions_are_off():
    assert read({}) == PortraitPreferences()
    for invalid in (False, [], {"emotion_palette": "yes"}, {"brightness": 200}):
        with pytest.raises(PreferencesConflictError):
            read({KEY: invalid})
        assert not effective(SimpleNamespace(entity_states={KEY: invalid})).enabled


def test_catalog_respects_scene_visibility_and_presence():
    def npc(identifier, scene="HERE", **attrs):
        return SimpleNamespace(
            id=identifier,
            name=identifier,
            current_scene_id=scene,
            entity_type="NPC",
            is_hidden=False,
            **attrs,
        )

    state = SimpleNamespace(
        current_scene_id="HERE",
        entity_states={
            KEY: {"emotion_palette": True},
            "ABSENT": {"presence": "absent"},
            "HIDDEN": {"is_hidden": True},
        },
    )
    manager = SimpleNamespace(state=state)
    active = prepare(manager, [npc("RIN"), npc("ABSENT"), npc("HIDDEN"), npc("ELSEWHERE", "THERE")])
    assert active.catalog == {"RIN": "RIN"}
    assert "intensity: integer 0-100" in active.prompt
    assert "thought:" not in active.prompt


def test_message_state_is_bound_to_exact_prose_and_role():
    active = turn(emotion_palette=True)
    active.clean(response())
    cue = active.payload(BODY)
    assert public_cues(cue, BODY) == cue
    assert public_cues(cue, "rewritten") is None
    assert public_cues({**cue, "version": 2}, BODY) is None
    for role in ("assistant", "user", "system"):
        message = ChatMessage(role=role, content=BODY, portrait_state=cue)
        assert message.to_client_dict()["portrait_state"] == (cue if role == "assistant" else None)
    assert (
        ChatMessage(role="assistant", content="Legacy").to_client_dict()["portrait_state"] is None
    )


def test_oversized_cast_and_duplicate_ids_are_bounded():
    active = turn(emotion_palette=True)
    active.clean(response([ENTRY] * 21))
    assert active.payload(BODY) is None
    active.clean(response([ENTRY, {**ENTRY, "emotion": "joy"}]))
    assert len(active.payload(BODY)["npcs"]) == 1
    assert active.payload(BODY)["npcs"]["RIN"]["emotion"] == "fear"
    stream = FooterStream()
    stream.feed(BODY + "<npc-state>" + "a" * (MAX_FOOTER + 1))
    assert stream.overflow and stream.footer == ""
