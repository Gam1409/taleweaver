"""Transport formatting tolerance never repairs facts, identifiers or JSON syntax."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import inference, perception
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import Projection, Settings, Usage

BODY = '{"audience":[{"actor_id":"npc","quotes":["Hello"],"uncertain":false}]}'


def host(text):
    llm = SimpleNamespace(
        max_tokens=4096,
        enable_thinking=False,
        model="mock",
        request_timeout=10,
        aexecute_simple_task=AsyncMock(return_value=text),
    )
    return SimpleNamespace(user=None, game_id=None, _chpm_model_factory=lambda role: llm)


@pytest.mark.parametrize("text", [BODY, "```json\n" + BODY + "\n```", "```\n" + BODY + "\n```"])
async def test_accepts_only_complete_json_or_one_outer_markdown_wrapper(text):
    usage = Usage()
    result = await inference.request(
        host(text), Settings(), usage, "Instruction", {}, Projection, "test"
    )
    assert result.audience[0].actor_id == "npc"
    assert usage.calls == 1 and usage.output_chars == len(text)


@pytest.mark.parametrize(
    "text",
    [
        "Explanation\n" + BODY,
        BODY + BODY,
        "```json\n" + BODY,
        "```json\n" + BODY[:-2] + "\n```",
        BODY.replace('"uncertain":false', '"uncertain":"false"'),
    ],
)
async def test_invalid_or_ambiguous_output_is_not_repaired(text):
    with pytest.raises(ChpmError):
        await inference.request(
            host(text), Settings(), Usage(), "Instruction", {}, Projection, "test"
        )


async def test_display_name_never_replaces_actor_id_even_in_valid_json():
    with pytest.raises(ChpmError, match="every present selected NPC"):
        await perception.project(
            host(BODY.replace('"npc"', '"Mara"')), Settings(), Usage(), "Hello", {"npc": "Mara"}
        )


@pytest.mark.parametrize(
    "body",
    [
        '{"audience":[],"audience":[]}',
        '{"audience":[{"actor_id":"npc","actor_id":"other","quotes":[]}]}',
        '{"audience":NaN}',
        '{"audience":Infinity}',
        '{"audience":-Infinity}',
    ],
)
async def test_duplicate_keys_and_nonstandard_numbers_fail_closed(body):
    with pytest.raises(ChpmError):
        await inference.request(
            host(body), Settings(), Usage(), "Instruction", {}, Projection, "test"
        )


def test_dynamic_id_enum_does_not_mutate_shared_schema():
    from backend.engine.chpm.json_contract import response_schema
    from backend.engine.chpm.schema import Verdict

    constrained = response_schema(Verdict, {"actor_id": ["a", "b"], "speaker_id": ["c"]})
    assert constrained["$defs"]["SpokenEvidence"]["properties"]["actor_id"]["enum"] == ["a", "b"]
    assert constrained["$defs"]["HeardSpeech"]["properties"]["speaker_id"]["enum"] == ["c"]
    assert (
        "enum"
        not in Verdict.model_json_schema()["$defs"]["SpokenEvidence"]["properties"]["actor_id"]
    )


def test_compact_schema_retains_a_real_title_field_and_its_constraints():
    from pydantic import BaseModel, Field

    from backend.engine.chpm.json_contract import response_schema

    class Titled(BaseModel):
        title: str = Field(min_length=2, max_length=10)

    result = response_schema(Titled, None)
    assert "title" not in result
    assert result["properties"]["title"] == {"type": "string", "minLength": 2, "maxLength": 10}
    assert result["required"] == ["title"]


def test_candidate_map_normalizes_to_existing_stored_contract():
    from backend.engine.chpm.json_contract import parse
    from backend.engine.chpm.schema import Proposal, ProposalOptions

    result = parse(
        ProposalOptions,
        '{"appraisal":"A decision","candidates":{'
        '"DEFER":{"intention":"Wait","reconsider_if":"Asked directly"},'
        '"CONTINUE":{"intention":"Discuss the plan","reconsider_if":"Plan changes"}}}',
    ).canonical()
    assert isinstance(result, Proposal)
    assert [candidate.kind for candidate in result.candidates] == ["CONTINUE", "DEFER"]
    assert Proposal.model_validate_json(result.model_dump_json()) == result


def test_candidate_duplicate_keys_and_wrong_action_are_not_silently_chosen():
    from backend.engine.chpm.json_contract import parse
    from backend.engine.chpm.schema import ProposalOptions

    for keys in (("DEFER", "DEFER"), ("DELETE", "CONTINUE")):
        entries = [
            f'"{key}":{{"intention":"Wait","reconsider_if":"Asked directly"}}' for key in keys
        ]
        raw = '{"appraisal":"A decision","candidates":{' + ",".join(entries) + "}}"
        with pytest.raises(ValueError):
            parse(ProposalOptions, raw)


def test_reference_schema_has_nullable_enum_and_rejects_invented_quote_fields():
    from backend.engine.chpm.json_contract import parse, response_schema
    from backend.engine.chpm.passages import Review

    schema = response_schema(Review, {"passage_id": ["p0", "p1"]})
    assert schema["$defs"]["Reference"]["properties"]["passage_id"]["enum"] == ["p0", "p1", None]
    with pytest.raises(ValueError):
        parse(Review, '{"matches":true,"evidence":[{"actor_id":"npc","quote":"Invented"}]}')
