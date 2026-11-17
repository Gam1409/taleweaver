"""Bounded logical requests through the existing shared inference router."""

import asyncio
import json
import logging
from copy import deepcopy
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from backend.core.llm_completion_capture import Completion, capture_completions
from backend.core.llm_router import GameMasterLLM
from backend.core.llm_schema_choices import SchemaChoiceError
from backend.core.llm_schema_compaction import share_schema
from backend.engine.chpm import (
    json_contract,
    parallel_budget,
    performance,
    tool_profiles,
    wire_normalization,
)
from backend.engine.chpm.errors import InferenceUnavailableError, RecoverableChpmError
from backend.engine.chpm.schema import Settings, Usage

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger(__name__)


class InvalidResponseError(RecoverableChpmError):
    """A completed model response failed validation; transport failures are separate."""

    def __init__(self, message: str, *, candidate: dict | None = None) -> None:
        super().__init__(message)
        self.candidate = candidate


class OutputBudgetError(RecoverableChpmError):
    """Do not repeat a cut-off response with the same output budget."""


class ToolEnvelopeError(InvalidResponseError):
    """A completed structural error that the owning workflow may explain once."""

    def __init__(self, message: str, *, code: str = "invalid_structure") -> None:
        super().__init__(message)
        self.code = code


def check_output_budget(
    records: list[Completion], limit: int, phase: str, *, invalid_json: bool = False
) -> None:
    if len(records) != 1:
        return
    record = records[0]
    explicit = any(
        isinstance(reason, str) and reason in {"length", "max_tokens"}
        for reason in (record.finish_reason, record.tool_finish_reason)
    )
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
    try:
        contract = share_schema(
            json_contract.response_schema(schema, identifiers), short_names=True
        )
    except SchemaChoiceError as exc:
        raise RecoverableChpmError(
            "CHPM has no usable source-bound contract. No request was sent; no decision was applied."
        ) from exc
    prompt = (
        instruction + "\nReturn one JSON object only, without Markdown fences or commentary. "
        "Use exact enum values for identifiers, never display names.\nJSON schema:\n"
        + json.dumps(
            contract,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return prompt, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def model_for(manager: Any, role: str, router: Any) -> Any:
    """Allow an isolated evaluation host to supply an instrumented cognitive port."""
    factory = getattr(manager, "_chpm_model_factory", None)
    return factory(role) if callable(factory) else router.for_role(manager.user, role)


def fits(
    settings: Settings, instruction: str, payload: dict, schema: type[BaseModel], identifiers: dict
) -> bool:
    """Optional source enrichment must fit the existing request limit without reserving a call."""
    prompt, content = compose(instruction, payload, schema, identifiers)
    return len(prompt) + len(content) <= settings.max_input_chars


def transport_options(router: Any, schema: type[BaseModel], identifiers: dict | None) -> dict:
    """Reuse the same output policy as all other technical router requests."""
    from backend.core.llm_structured_output import for_router

    selected = for_router(
        router,
        schema,
        schema=json_contract.response_schema(schema, identifiers, explicit_keys=True),
    ).response_format
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
        candidate, corrections = wire_normalization.normalize(schema, candidate, identifiers)
        usage.format_repairs += len(corrections)
        # Shape errors and the existing choice-ground hint share one bounded repair.
        # Check handles against the untouched raw object before canonical conversion.
        parsed = schema.model_validate(deepcopy(candidate))
        json_contract.validate_identifiers(schema, candidate, identifiers)
        if corrections:
            logger.info("CHPM wire format corrected: phase=%s fields=%s", phase, corrections)
        return parsed
    except ValueError as exc:
        check_output_budget(
            completions, llm.max_tokens, phase, invalid_json=isinstance(exc, json.JSONDecodeError)
        )
        raise InvalidResponseError(
            f"CHPM {phase} response invalid: {validation_feedback(exc)}", candidate=candidate
        ) from exc


async def tool_request(
    manager: Any,
    settings: Settings,
    usage: Usage,
    messages: list[dict],
    tools: list[dict],
    *,
    llm: Any,
    phase: str = "agent_lookup",
    output_limit: int = 768,
) -> Any:
    """Reserve one native round through the same deadlines, admission and timings."""
    from backend.core.llm_tool_turn import InvalidToolTurnError

    if getattr(llm, "protocol", "native") != "json":
        tool_profiles.validate_native(settings.tool_profile, tools)
    sizing = getattr(llm, "input_size", None)
    size = (
        sizing(messages, tools)
        if callable(sizing)
        else len(json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False))
    )
    reserve(settings, usage, size)
    parallel_budget.dispatched(phase)
    llm.max_tokens = min(llm.max_tokens, settings.max_output_tokens, output_limit)
    llm.enable_thinking = False
    try:
        with performance.measure(usage, phase), capture_completions() as completions:
            result = await asyncio.wait_for(
                llm.aexecute_tool_turn(
                    messages,
                    tools,
                    llm.model,
                    game_id=manager.game_id,
                    operation="chpm",
                    phase=phase,
                ),
                timeout=float(llm.request_timeout),
            )
    except InvalidToolTurnError as exc:
        check_output_budget(completions, llm.max_tokens, phase, invalid_json=True)
        rejected_finish = exc.code == "unsupported_finish" or any(
            record.tool_rejected for record in completions
        )
        if rejected_finish:
            raise InvalidResponseError("CHPM received an unsupported tool completion.") from exc
        raise ToolEnvelopeError("CHPM received an invalid tool envelope.", code=exc.code) from exc
    except Exception as exc:
        raise InferenceUnavailableError(
            f"CHPM {phase} failed ({type(exc).__name__}). No tool request was applied."
        ) from exc
    reason = result.finish_reason
    if reason is not None and (
        not isinstance(reason, str) or reason not in {"stop", "tool_calls", "length", "max_tokens"}
    ):
        raise InvalidResponseError("CHPM native tool response did not complete normally.")
    check_output_budget(completions, llm.max_tokens, phase)
    if result.finish_reason in {"length", "max_tokens"}:
        raise OutputBudgetError("CHPM native tool response was truncated; no retry was sent.")
    usage.output_chars += len(json.dumps(result.assistant_message, ensure_ascii=False))
    return result


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
