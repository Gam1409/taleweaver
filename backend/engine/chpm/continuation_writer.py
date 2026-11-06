"""One bounded ordinary narrator call for text already rejected by CHPM review."""

import asyncio
import json
from typing import TYPE_CHECKING, Any

from backend.core.llm_completion_capture import capture_completions
from backend.core.llm_router import GameMasterLLM
from backend.engine.chpm import continuation, inference
from backend.engine.chpm.errors import ChpmError
from backend.engine.npc_presentation.runtime import clean_candidate

if TYPE_CHECKING:
    from backend.engine.chpm.runtime import Turn


async def generate(
    manager: Any,
    turn: "Turn",
    resolution: str,
    system_prompt: str,
    narration_messages: list[dict[str, str]] | None = None,
    ordinary_context: str = "",
) -> str:
    if turn.usage.fallback_requests:
        raise ChpmError("The single ordinary RP continuation was already used.")
    turn.usage.fallback_requests = 1
    # Reuse ordinary history, replacing only the current message that contained
    # rejected CHPM intentions. Do not include the rejected prose as story history.
    messages = [dict(row) for row in (narration_messages or [])[:-1]]
    if not messages:
        messages = [{"role": "system", "content": system_prompt}]
    messages.append(
        {
            "role": "user",
            "content": json.dumps(
                {
                    "current_scene_and_resolution": ordinary_context or resolution,
                    "player_request": turn.player_request,
                    "rp_continuation": continuation.contract(turn),
                    "review_issues_to_avoid": turn.fallback_issues,
                },
                ensure_ascii=False,
            ),
        }
    )
    llm = inference.model_for(manager, "complex", GameMasterLLM)
    llm.enable_thinking = False
    llm.max_tokens = min(llm.max_tokens, 4096)
    with capture_completions() as records:
        result = await asyncio.wait_for(
            llm.aexecute_simple_task(
                system_prompt,
                messages[-1]["content"],
                llm.model,
                messages=messages,
                game_id=manager.game_id,
                operation="chpm",
                phase="rp_continuation",
            ),
            timeout=float(llm.request_timeout),
        )
    inference.check_output_budget(records, llm.max_tokens, "rp_continuation")
    if isinstance(result, str):
        result = clean_candidate(manager, result)
    if not isinstance(result, str) or not result.strip():
        raise ChpmError("The narrator could not produce the ordinary RP continuation.")
    return result
