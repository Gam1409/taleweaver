"""Bounded logical requests through the existing shared inference router."""

import asyncio
import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from backend.core.llm_completion_capture import Completion, capture_completions
from backend.core.llm_router import GameMasterLLM
from backend.engine.chpm import json_contract, parallel_budget, performance
from backend.engine.chpm.errors import InferenceUnavailableError, RecoverableChpmError
from backend.engine.chpm.schema import Settings, Usage

T = TypeVar("T", bound=BaseModel)


class InvalidResponseError(RecoverableChpmError):
    """A completed model response failed validation; transport failures are separate."""

    def __init__(self, message: str, *, candidate: dict | None = None) -> None:
        super().__init__(message)
        self.candidate = candidate


class OutputBudgetError(RecoverableChpmError):
    """Do not repeat a cut-off response with the same output budget."""


def check_output_budget(
    records: list[Completion], limit: int, phase: str, *, invalid_json: bool = False
) -> None:
    if len(records) != 1:
        return
    record = records[0]
    explicit = record.finish_reason in {"length", "max_tokens"}
    inferred = (
        invalid_json
        and record.finish_reason is None
        and record.completion_tokens is not None
        and record.completion_tokens >= limit
    )
    if explicit or inferred:
        raise OutputBudgetError(
            f"CHPM {phase} exhausted its output budget ({limit} tokens). "
            "No automatic retry with the same budget was sent. Increase the CHPM and model-role "
            "output limits together, accounting for server/proxy timeouts. No decision was applied."
        )


def validation_feedback(error: ValueError) -> str:
    if isinstance(error, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)[:4]
        )[:600]
    return str(error)[:600]


def compose(
    instruction: str, payload: dict, schema: type[BaseModel], identifiers: dict | None
) -> tuple[str, str]:
    prompt = (
        instruction + "\nReturn one JSON object only, without Markdown fences or commentary. "
        "Use exact enum values for identifiers, never display names.\nJSON schema:\n"
        + json.dumps(
            json_contract.response_schema(schema, identifiers),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return prompt, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def model_for(manager: Any, role: str, router: Any) -> Any:
    """Allow an isolated evaluation host to supply an instrumented cognitive port."""
    factory = getattr(manager, "_chpm_model_factory", None)
    return factory(role) if callable(factory) else router.for_role(manager.user, role)


def transport_options(router: Any, schema: type[BaseModel], identifiers: dict | None) -> dict:
    """Honor the custom connection's existing explicit structured-output capability."""
    if getattr(router, "provider", None) != "custom_openai":
        return {}
    from backend.core.custom_openai import structured_response_format

    selected = structured_response_format(
        router, schema, schema=json_contract.response_schema(schema, identifiers)
    )
    return {"response_format": selected} if selected is not None else {}


async def request(
    manager: Any,
    settings: Settings,
    usage: Usage,
    instruction: str,
    payload: dict,
    schema: type[T],
    phase: str,
    *,
    identifiers: dict[str, list[str]] | None = None,
) -> T:
    prompt, content = compose(instruction, payload, schema, identifiers)
    reserve(settings, usage, len(prompt) + len(content))
    parallel_budget.dispatched(phase)
    llm = model_for(manager, settings.model_role, GameMasterLLM)
    llm.max_tokens = min(llm.max_tokens, settings.max_output_tokens)
    llm.enable_thinking = False
    try:
        with performance.measure(usage, phase), capture_completions() as completions:
            result = await asyncio.wait_for(
                llm.aexecute_simple_task(
                    prompt,
                    content,
                    llm.model,
                    game_id=manager.game_id,
                    operation="chpm",
                    phase=phase,
                    **transport_options(llm, schema, identifiers),
                ),
                timeout=float(llm.request_timeout),
            )
        usage.output_chars += len(result)
    except Exception as exc:
        raise InferenceUnavailableError(
            f"CHPM {phase} failed ({type(exc).__name__}). No decision was applied."
        ) from exc
    check_output_budget(completions, llm.max_tokens, phase)
    candidate = None
    try:
        candidate = json_contract.decode(result)
        return schema.model_validate(candidate)
    except ValueError as exc:
        check_output_budget(
            completions, llm.max_tokens, phase, invalid_json=isinstance(exc, json.JSONDecodeError)
        )
        raise InvalidResponseError(
            f"CHPM {phase} response invalid: {validation_feedback(exc)}", candidate=candidate
        ) from exc


def reserve(settings: Settings, usage: Usage, size: int) -> None:
    if size > settings.max_input_chars:
        raise RecoverableChpmError(
            f"CHPM input exceeds its configured size limit ({size} > {settings.max_input_chars} characters). No decision was applied."
        )
    if usage.calls >= settings.max_calls_per_turn:
        raise RecoverableChpmError(
            "CHPM request budget exhausted. No unvalidated response was published."
        )
    usage.calls += 1
    usage.input_chars += size
