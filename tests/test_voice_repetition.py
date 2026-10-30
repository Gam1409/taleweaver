"""Repeated delivery cues cannot consume the dialogue; ordinary cues remain intact."""

from types import SimpleNamespace

import pytest

from backend.core.llm_stream_filters import clean_stream_voice_tags
from backend.core.voice_repetition import (
    VoiceRepetitionFilter,
    clean_voice_history,
    clean_voice_repetition,
)

LOOP = "<giggles><short pause><throat-clearing><breath><long pause><mischievously>"


def test_runaway_chain_keeps_speech_and_next_legitimate_cues():
    text = LOOP * 20 + "Спасибо." + "<breath>" * 20 + "За всё."
    result = clean_voice_repetition(text)
    assert result.count("<") == 10
    assert result.endswith("<breath><breath>За всё.")
    assert "Спасибо." in result
    assert result.count("<giggles>") == 2


@pytest.mark.parametrize(
    "text",
    [
        "<cough><cough> Excuse me. <short pause> Thank you.",
        '[curious] "<breath> Hello."\nNPC: [calm] "<breath> Welcome."',
        "<unknown><unknown><unknown> 2 < 3 and 5 > 4.",
        "Ordinary text with a partial <bre",
        "A mathematical <" + "x" * 80,
    ],
)
def test_ordinary_tags_unknown_markup_and_incomplete_text_are_preserved(text):
    assert clean_voice_repetition(text) == text


@pytest.mark.parametrize("size", [1, 2, 7, 31, 1000])
def test_filter_is_independent_of_token_boundaries(size):
    text = "Miki: " + LOOP * 20 + "Thank you. <breath> Goodbye. <partial"
    cleaner = VoiceRepetitionFilter()
    result = "".join(cleaner.feed(text[i : i + size]) for i in range(0, len(text), size))
    assert result + cleaner.finish() == clean_voice_repetition(text)


def test_history_cleanup_does_not_rewrite_user_input_or_saved_assistant_messages():
    original = LOOP * 20 + "Thank you."
    messages = [
        {"role": "system", "content": original},
        {"role": "user", "content": original},
        {"role": "assistant", "content": original},
    ]
    result = clean_voice_history(messages)
    assert result[:2] == messages[:2]
    assert result[2]["content"] == clean_voice_repetition(original)
    assert messages[2]["content"] == original


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_stream_keeps_words_and_flushes_partial_text_on_failure(fail):
    text = "Opening words. " + LOOP * 10 + "Thank you. <bre"

    async def source():
        for char in text:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=char))])
        if fail:
            raise RuntimeError("provider failed")

    result = []
    try:
        async for chunk in clean_stream_voice_tags(source(), lambda value: value):
            result.append(chunk.choices[0].delta.content)
    except RuntimeError:
        assert fail
    else:
        assert not fail
    assert "".join(result) == clean_voice_repetition(text)


def test_whitespace_does_not_restart_a_tag_only_loop():
    result = clean_voice_repetition(("<breath>\n" * 20) + "Hello.")
    assert result.count("<breath>") == 2
    assert result.endswith("Hello.")


@pytest.mark.asyncio
async def test_partial_tag_is_flushed_before_terminal_chunk_and_usage_is_preserved():
    async def source():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(delta=SimpleNamespace(content="Hello. <bre"), finish_reason=None)
            ]
        )
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason="stop")]
        )
        yield SimpleNamespace(choices=[], usage={"total_tokens": 25})

    chunks = [chunk async for chunk in clean_stream_voice_tags(source(), lambda value: value)]
    text = "".join(chunk.choices[0].delta.content or "" for chunk in chunks if chunk.choices)
    assert text == "Hello. <bre"
    assert chunks[-1].usage == {"total_tokens": 25}
    assert chunks[-2].choices[0].finish_reason == "stop"
