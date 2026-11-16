"""Measure the actual progression model call separately from host resolution."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel

from backend.core.llm_logger import log_structured_event

if TYPE_CHECKING:
    from backend.core.llm_router import GameMasterLLM

T = TypeVar("T", bound=BaseModel)


async def request(
    manager: Any, llm: GameMasterLLM, system: str, user: str, response_model: type[T], *, model: str
) -> T:
    context = {
        "adventure_id": manager.adventure.id,
        "game_id": manager.game_id,
        "operation": "chat_turn",
        "phase": "chat_progression",
    }
    # Characters are a size signal, not a tokenizer-dependent token estimate.
    schema_chars = len(json.dumps(response_model.model_json_schema(), ensure_ascii=False))
    log_structured_event(
        "gm.turn.pipeline.context", **context, chars=len(system) + len(user) + schema_chars
    )
    started = time.perf_counter()
    try:
        return await llm.aexecute_complex_task(
            system, user, response_model=response_model, model=model, **context
        )
    finally:
        # Includes SDK retries and admission waits. Per-call LLM diagnostics and the
        # inference queue distinguish those from remote generation; this is wall time.
        log_structured_event(
            "gm.turn.pipeline.pass",
            **context,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
