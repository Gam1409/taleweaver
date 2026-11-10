"""A valid technical document must never be rewritten as narrated dialogue."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from backend.core.llm_router import GameMasterLLM
from backend.models.user import User


class Quote(BaseModel):
    quote: str


def router():
    return GameMasterLLM(
        User(username="test", llm_settings={}, encrypted_api_keys={}), provider="ollama"
    )


def response(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
        model_dump=lambda: {},
    )


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("prefix", ["", "<think>Planning.</think>\n", "Planning.\n</think>\n"])
async def test_technical_reply_keeps_voice_tags_as_literal_data(monkeypatch, structured, prefix):
    raw = json.dumps({"quote": "[whispers] Wait here."}, indent=2)
    llm = router()
    completion = AsyncMock(return_value=response(prefix + raw))
    monkeypatch.setattr(llm, "_acompletion_with_openrouter_fallback", completion)
    options = {"response_format": {"type": "json_object"}} if structured else {"operation": "chpm"}
    result = await llm.aexecute_simple_task("Extract JSON.", "Wait here.", "local-model", **options)
    assert result == raw
    assert json.loads(result)["quote"] == "[whispers] Wait here."
    completion.assert_awaited_once()


@pytest.mark.parametrize("prefix", ["", "<think>Planning.</think>\n", "Planning.\n</think>\n"])
@pytest.mark.parametrize(
    "quote",
    [
        "A literal <think> label.",
        "A literal </think> label.",
        "A literal <think>memo</think> label.",
        "Example: ```json {x} ```",
        "Use , ] and , } literally.",
    ],
)
def test_structured_parser_keeps_literal_tags_fences_and_delimiters(quote, prefix):
    raw = json.dumps({"quote": quote})
    result = router()._parse_structured_content(response(prefix + raw), Quote)
    assert result.quote == quote
    assert GameMasterLLM._repair_json(raw) == raw


async def test_plain_narration_still_normalizes_a_speaker_voice_tag(monkeypatch):
    llm = router()
    monkeypatch.setattr(
        llm,
        "_acompletion_with_openrouter_fallback",
        AsyncMock(return_value=response('Mira: "[WHISPERS] Wait here."')),
    )
    result = await llm.aexecute_simple_task("Narrate.", "Wait.", "local-model")
    assert result == 'Mira: [whispers] "Wait here."'


async def test_technical_input_examples_preserve_literal_source_cues(monkeypatch):
    llm = router()
    raw = json.dumps({"quote": "The note literally contains <sigh>."})
    completion = AsyncMock(return_value=response(raw))
    monkeypatch.setattr(llm, "_acompletion_with_openrouter_fallback", completion)
    messages = [
        {"role": "assistant", "content": raw},
        {"role": "user", "content": "Use the exact quotation."},
    ]
    await llm.aexecute_simple_task(
        "Extract.", "Quote.", "local-model", messages=messages, operation="chpm"
    )
    assert completion.call_args.args[0]["messages"] == messages
