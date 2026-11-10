"""Technical requests share provider policy; narration stays freeform."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict, Field, create_model

from backend.core.llm_structured_output import select
from backend.engine.chpm.inference import transport_options


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: str


@pytest.mark.parametrize(
    "provider,model,expected",
    [
        ("ollama", "local-model", "json_schema"),
        ("openai", "gpt-4o-mini", "json_schema"),
        ("google", "gemini-2.5-flash", "json_schema"),
        ("gemini", "gemini-2.5-flash", "json_schema"),
        ("deepseek", "deepseek-chat", "json_object"),
        ("anthropic", "claude-sonnet", "json_schema"),
        ("openrouter", "vendor/model", "json_object"),
        ("kimi", "moonshot-v1", "json_object"),
        ("minimax", "MiniMax-M2", None),
    ],
)
def test_npc_requests_use_the_existing_provider_output_policy(provider, model, expected):
    router = SimpleNamespace(provider=provider, model=model)
    options = transport_options(router, Reply, {"actor_id": ["known_npc"]})
    if expected is None:
        assert options == {}
        return
    assert options["response_format"]["type"] == expected
    if expected == "json_schema":
        contract = options["response_format"]["json_schema"]["schema"]
        assert contract["properties"]["actor_id"]["enum"] == ["known_npc"]
        assert contract["additionalProperties"] is False


def test_a_test_double_without_provider_does_not_gain_transport_parameters():
    assert transport_options(SimpleNamespace(), Reply, {"actor_id": ["known_npc"]}) == {}


def test_openai_variable_candidate_map_uses_json_mode_without_expanding_the_decision():
    from backend.engine.chpm.proposal_draft import Draft

    output = select("openai", "gpt-4o-mini", Draft)
    assert output.mode == "json_object"
    assert output.response_format == {"type": "json_object"}
    assert output.local_checks == ("schema_projection",)


def test_anthropic_open_dictionary_uses_prompt_instead_of_claiming_json_mode():
    class DynamicReply(BaseModel):
        model_config = ConfigDict(extra="forbid")
        facts: dict[str, str]

    output = select("anthropic", "claude-sonnet", DynamicReply)
    assert output.mode == "prompt" and output.response_format is None
    assert output.local_checks == ("schema_projection",)


@pytest.mark.parametrize("count,expected", [(24, "json_schema"), (25, "prompt")])
def test_anthropic_optional_parameter_limit_is_checked_before_generation(count, expected):
    model = create_model(
        "OptionalFields",
        __config__=ConfigDict(extra="forbid"),
        **{f"field{i}": (str, "") for i in range(count)},
    )
    assert select("anthropic", "claude-sonnet", model).mode == expected


@pytest.mark.parametrize("count,expected", [(16, "json_schema"), (17, "prompt")])
def test_anthropic_union_parameter_limit_is_checked_before_generation(count, expected):
    model = create_model(
        "UnionFields",
        __config__=ConfigDict(extra="forbid"),
        **{f"field{i}": (str | None, None) for i in range(count)},
    )
    assert select("anthropic", "claude-sonnet", model).mode == expected


def test_deferred_text_rule_remains_in_the_prompt_and_the_canonical_validator(monkeypatch):
    from pydantic import ValidationError

    from tests.test_custom_openai import make_router

    class ConstrainedReply(BaseModel):
        model_config = ConfigDict(extra="forbid")
        code: str = Field(pattern=r"^[A-Z]+$")

    router = make_router()
    router.provider = "openai"
    built = router._build_structured_request(
        "Extract the code.", "ABC", ConstrainedReply, "gpt-4o-mini"
    )
    assert r"^[A-Z]+$" in built.system_prompt
    assert (
        "pattern"
        not in built.kwargs["response_format"]["json_schema"]["schema"]["properties"]["code"]
    )
    with pytest.raises(ValidationError):
        ConstrainedReply.model_validate({"code": "not a code"})
