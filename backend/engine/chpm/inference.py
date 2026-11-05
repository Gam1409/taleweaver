"""Bounded logical requests through the existing shared inference router."""

import asyncio
import json
from typing import Any, TypeVar

from pydantic import BaseModel

from backend.core.llm_router import GameMasterLLM
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import Settings, Usage

T = TypeVar("T", bound=BaseModel)


async def request(
    manager: Any,
    settings: Settings,
    usage: Usage,
    instruction: str,
    payload: dict,
    schema: type[T],
    phase: str,
) -> T:
    prompt = instruction + "\nJSON schema:\n" + json.dumps(schema.model_json_schema())
    content = json.dumps(payload, ensure_ascii=False)
    reserve(settings, usage, len(prompt) + len(content))
    llm = GameMasterLLM.for_role(manager.user, settings.model_role)
    llm.max_tokens = min(llm.max_tokens, settings.max_output_tokens)
    llm.enable_thinking = False
    try:
        result = await asyncio.wait_for(
            llm.aexecute_simple_task(
                prompt,
                content,
                llm.model,
                game_id=manager.game_id,
                operation="chpm",
                phase=phase,
            ),
            timeout=float(llm.request_timeout),
        )
        usage.output_chars += len(result)
        return schema.model_validate_json(result)
    except Exception as exc:
        raise ChpmError(
            f"CHPM {phase} failed ({type(exc).__name__}). No decision was applied."
        ) from exc


def reserve(settings: Settings, usage: Usage, size: int) -> None:
    if size > settings.max_input_chars:
        raise ChpmError("CHPM input exceeds its configured size limit. No decision was applied.")
    if usage.calls >= settings.max_calls_per_turn:
        raise ChpmError("CHPM request budget exhausted. No unvalidated response was published.")
    usage.calls += 1
    usage.input_chars += size
