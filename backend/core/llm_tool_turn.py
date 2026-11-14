"""Native tool turns through the shared admitted provider transport, without execution."""

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from backend.core.inference.admission import timeout_for
from backend.core.llm_finish_state import classify_tool_finish
from backend.core.llm_logger import log_llm_interaction, log_structured_event
from backend.core.llm_thinking import apply_thinking_settings


class NativeToolsUnsupportedError(RuntimeError):
    """The local adapter cannot retain required native-tool parameters before inference."""


class InvalidToolTurnError(ValueError):
    """A completed response does not contain an unambiguous native assistant message."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments_raw: str


@dataclass(frozen=True)
class ToolTurn:
    assistant_message: dict[str, Any]
    calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


def ensure_tools_supported(router: Any, model: str | None = None) -> None:
    """Reject a known local parameter drop before reserving or sending inference."""
    selected = model or router.model
    options: dict[str, Any] = {}
    router._apply_provider_options(options, selected)
    adapter = router._get_litellm()
    resolved, provider, _, _ = adapter.get_llm_provider(
        model=router._normalize_model(selected),
        custom_llm_provider=options.get("custom_llm_provider"),
        api_base=options.get("api_base"),
    )
    supported = adapter.get_supported_openai_params(model=resolved, custom_llm_provider=provider)
    if not {"tools", "tool_choice"}.issubset(supported or []):
        raise NativeToolsUnsupportedError(
            "The configured provider adapter does not support native tools and tool_choice."
        )


def _request_kwargs(
    router: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str,
    tool_choice: str | dict[str, Any],
) -> dict[str, Any]:
    kwargs = {
        "model": router._normalize_model(model),
        "messages": deepcopy(messages),
        "tools": deepcopy(tools),
        "tool_choice": tool_choice,
        "max_tokens": router.max_tokens,
        "drop_params": False,
        "num_retries": 0,
        "max_retries": 0,
        "_single_attempt": True,
    }
    apply_thinking_settings(
        kwargs, provider=router.provider, model=model, enabled=False, budget_tokens=0
    )
    router._apply_provider_options(kwargs, model)
    if router.provider == "ollama":
        kwargs["think"] = False
    router._apply_openrouter_provider_routing(kwargs)
    router._prepare_cacheable_messages(kwargs, kwargs["model"])
    return kwargs


async def single_attempt(router: Any, kwargs: dict[str, Any]) -> Any:
    """Run inside the common transport decorators, without uncertain-request retries."""
    clean = {key: value for key, value in kwargs.items() if key != "_single_attempt"}
    if router.provider == "custom_openai":
        from backend.core.custom_openai import acomplete

        return await acomplete(router, clean)
    return await router._get_litellm().acompletion(**clean, request_timeout=timeout_for(router))


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        result = dump()
        if isinstance(result, dict):
            return result
    raise InvalidToolTurnError("The native tool response must contain objects.")


def _call(value: Any) -> ToolCall:
    item = _mapping(value)
    function = _mapping(item.get("function"))
    identifier, name, arguments = item.get("id"), function.get("name"), function.get("arguments")
    if (
        item.get("type") != "function"
        or not isinstance(identifier, str)
        or not identifier
        or not isinstance(name, str)
        or not name
        or not isinstance(arguments, str)
    ):
        raise InvalidToolTurnError("A native function call requires an ID, name and raw arguments.")
    return ToolCall(identifier, name, arguments)


def _choice_finish_reason(choice: dict[str, Any]) -> str | None:
    try:
        return classify_tool_finish(choice)
    except ValueError as exc:
        raise InvalidToolTurnError(str(exc)) from None


def _turn(payload: dict[str, Any]) -> ToolTurn:
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise InvalidToolTurnError("A native tool response requires exactly one choice.")
    choice = _mapping(choices[0])
    message = _mapping(choice.get("message"))
    raw_calls = message.get("tool_calls")
    calls = [] if raw_calls is None else raw_calls
    if (
        message.get("role") != "assistant"
        or not isinstance(calls, list)
        or not isinstance(message.get("content"), (str, type(None)))
    ):
        raise InvalidToolTurnError("A native tool response requires an assistant message.")
    usage = payload.get("usage")
    return ToolTurn(
        message,
        tuple(_call(call) for call in calls),
        _choice_finish_reason(choice),
        usage if isinstance(usage, dict) else None,
    )


async def execute(
    router: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str,
    *,
    tool_choice: str | dict[str, Any] = "auto",
    adventure_id: str | None = None,
    game_id: str | None = None,
    operation: str | None = None,
    phase: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ToolTurn:
    """Keep assistant calls and arguments intact; callers validate and execute capabilities."""
    ensure_tools_supported(router, model)
    kwargs = _request_kwargs(router, messages, tools, model, tool_choice)
    context: dict[str, Any] = {
        "adventure_id": adventure_id,
        "game_id": game_id,
        "operation": operation,
        "phase": phase,
        "metadata": metadata,
    }
    log_structured_event(
        "gm.turn.request", model=kwargs["model"], provider=router.provider, **context
    )
    response = await router._acompletion_with_openrouter_fallback(kwargs)
    payload = _mapping(response)
    log_llm_interaction(
        model=model,
        provider=router.provider,
        system_prompt="",
        user_prompt=json.dumps(messages, ensure_ascii=False),
        response_content="",
        raw_response=payload,
        event_type="gm.turn.response",
        **context,
    )
    return _turn(payload)
