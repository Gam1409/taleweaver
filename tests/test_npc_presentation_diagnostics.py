"""Missing portrait data is observable without copying prose or guessing psychology."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.core.diagnostic_fields import safe_fields
from backend.core.npc_presentation import PortraitPreferences
from backend.core.system_diagnostics import DiagnosticService, service
from backend.engine.chpm import continuation
from backend.engine.chpm.inference import InvalidResponseError
from backend.engine.chpm.schema import Usage
from backend.engine.npc_presentation import diagnostics, runtime
from backend.engine.npc_presentation.runtime import PresentationTurn
from backend.engine.npc_presentation.stream import MAX_FOOTER

BODY = "PRIVATE_STORY_MUST_NOT_APPEAR_IN_DIAGNOSTICS"
ENTRY = {"npc_id": "RIN", "emotion": "interest", "intensity": 65, "thought": "PRIVATE_THOUGHT"}


def footer(entries):
    return "<npc-state>" + json.dumps({"npcs": entries}) + "</npc-state>"


@pytest.mark.parametrize(
    "suffix,reason",
    [
        ("", "missing_footer"),
        ("<npc-state>{", "incomplete_footer"),
        ("<npc-state>" + "x" * (MAX_FOOTER + 1), "footer_too_large"),
        ("<npc-state>oops</npc-state>", "invalid_json"),
        ('<npc-state>{"npcs":{}}</npc-state>', "invalid_entries"),
        (footer([{**ENTRY, "npc_id": "OTHER"}]), "no_valid_entries"),
        (footer([{**ENTRY, "intensity": "high", "thought": "x" * 161}]), "no_valid_entries"),
        (footer([ENTRY]), "available"),
    ],
)
@pytest.mark.parametrize("streamed", [False, True])
def test_final_candidate_reports_precise_reason_without_content(
    monkeypatch, caplog, suffix, reason, streamed
):
    turn = PresentationTurn(
        PortraitPreferences(emotion_palette=True, character_thoughts=True), {"RIN": "Rin"}
    )
    manager = SimpleNamespace(
        state=SimpleNamespace(session_id="session"), turn_id="turn", _portrait_presentation=turn
    )
    emit = Mock()
    monkeypatch.setattr(service, "emit", emit)
    with caplog.at_level(logging.INFO):
        visible = (
            turn.feed(BODY + suffix) + turn.finish() if streamed else turn.clean(BODY + suffix)
        )
        # CHPM validates prose that has already had its private footer removed.
        visible = turn.clean(visible)
        runtime.diagnose(manager, visible, completed=True)
    (event,) = emit.call_args.args
    fields = emit.call_args.kwargs
    assert event == "npc.presentation"
    assert fields["presentation_reason"] == reason
    assert fields["candidates"] == 1
    assert fields["selected_count"] == int(reason == "available")
    assert fields["presentation_reason"] == safe_fields(fields)["presentation_reason"]
    assert reason in caplog.text
    assert BODY not in caplog.text and ENTRY["thought"] not in caplog.text
    assert BODY not in json.dumps(fields) and ENTRY["thought"] not in json.dumps(fields)


@pytest.mark.parametrize(
    "preferences,cast,completed,text,expected",
    [
        ({}, {"RIN": "Rin"}, True, BODY, "disabled"),
        ({"emotion_palette": True}, {}, True, BODY, "no_visible_cast"),
        ({"emotion_palette": True}, {"RIN": "Rin"}, False, BODY, "incomplete_narration"),
        ({"emotion_palette": True}, {"RIN": "Rin"}, True, "Replaced story", "source_mismatch"),
    ],
)
def test_diagnostic_distinguishes_settings_cast_and_replaced_prose(
    monkeypatch, preferences, cast, completed, text, expected
):
    turn = PresentationTurn(PortraitPreferences(**preferences), cast)
    turn.clean(BODY + footer([ENTRY]))
    manager = SimpleNamespace(
        state=SimpleNamespace(session_id="session"), _portrait_presentation=turn
    )
    emit = Mock()
    monkeypatch.setattr(service, "emit", emit)
    runtime.diagnose(manager, text, completed=completed)
    assert emit.call_args.kwargs["presentation_reason"] == expected


def test_english_metadata_keys_are_explicit_and_reminded_independently_of_story_language():
    turn = PresentationTurn(
        PortraitPreferences(emotion_palette=True, character_thoughts=True), {"RIN": "Rin"}
    )
    assert "English" in turn.prompt and "JSON keys" in turn.prompt
    assert "private footer" in turn.reminder
    assert "npc_id" in turn.reminder
    assert "emotion" in turn.reminder and "intensity" in turn.reminder
    assert "thought" in turn.reminder
    assert "English" in turn.reminder
    assert PresentationTurn(PortraitPreferences(), {"RIN": "Rin"}).reminder == ""
    assert PresentationTurn(PortraitPreferences(emotion_palette=True), {}).reminder == ""
    assert (
        "thought"
        not in PresentationTurn(PortraitPreferences(emotion_palette=True), {"RIN": "Rin"}).reminder
    )


def test_system_log_retains_the_reason_without_story_or_thought_text(tmp_path, monkeypatch):
    log = DiagnosticService(tmp_path / "diagnostics")
    monkeypatch.setattr(diagnostics, "service", log)
    turn = PresentationTurn(PortraitPreferences(emotion_palette=True), {"RIN": "Rin"})
    turn.clean(BODY + footer([ENTRY]))
    manager = SimpleNamespace(
        state=SimpleNamespace(session_id="session"), _portrait_presentation=turn
    )
    try:
        log.set_enabled(True)
        runtime.diagnose(manager, BODY, completed=True)
    finally:
        log.close()
    text = (log.directory / "system-debug.jsonl").read_text()
    record = next(
        json.loads(line)
        for line in text.splitlines()
        if json.loads(line)["event"] == "npc.presentation"
    )
    assert record["presentation_reason"] == "available"
    assert record["candidates"] == record["selected_count"] == 1
    assert BODY not in text and ENTRY["thought"] not in text


def test_fallback_reason_and_failure_type_reach_debug_without_exception_content(
    tmp_path, monkeypatch
):
    log = DiagnosticService(tmp_path / "diagnostics")
    monkeypatch.setattr(continuation, "service", log)
    turn = SimpleNamespace(usage=Usage())
    try:
        log.set_enabled(True)
        try:
            raise InvalidResponseError(BODY)
        except InvalidResponseError as error:
            continuation.activate(turn, "analysis_failed", error=error)
    finally:
        log.close()
    text = (log.directory / "system-debug.jsonl").read_text()
    record = next(
        json.loads(line)
        for line in text.splitlines()
        if json.loads(line)["event"] == "npc.behavior_fallback"
    )
    assert record["fallback_reason"] == "analysis_failed"
    assert record["error"]["type"] == "InvalidResponseError"
    assert (
        record["error"]["frames"][-1]["function"]
        == "test_fallback_reason_and_failure_type_reach_debug_without_exception_content"
    )
    assert BODY not in text
