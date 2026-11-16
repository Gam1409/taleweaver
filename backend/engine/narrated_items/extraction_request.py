"""At most one conservative correction within the original extraction deadline."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from backend.core.llm_structured_execution import InputBudgetError
from backend.engine.narrated_items import correction_input, extraction_repair, reference_schema
from backend.engine.narrated_items.diagnostics import describe_failure
from backend.engine.narrated_items.schema import ItemExtraction, SharedItemExtraction
from backend.engine.narrated_items.source_catalog import Catalog


@dataclass(frozen=True)
class Result:
    extraction: Any
    repair: dict | None = None


async def request(
    llm: Any,
    instructions: str,
    payload: str,
    catalog: Catalog,
    *,
    game_id: str,
    staging: bool,
    timeout: float,
    max_context: int,
    accept: Callable[[ItemExtraction, ItemExtraction], Awaitable[bool]],
    correction_policy: correction_input.Policy | None = None,
) -> Result:
    """Keep initial payload admission; additionally bound the correction's prepared wire.

    The legacy initial request does not acquire a new total-wire limit in this path.
    No retry follows an incomplete initial response or any transport failure.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    response_schema = reference_schema.build(
        SharedItemExtraction if staging else ItemExtraction, catalog, complete=True
    )
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError("State extraction deadline expired before request admission.")
    original = await asyncio.wait_for(
        llm.aexecute_complex_task(
            instructions,
            payload,
            SharedItemExtraction,
            llm.model,
            game_id=game_id,
            operation="narrated_items",
            phase="reconciliation",
            response_schema=response_schema,
            single_attempt=True,
        ),
        timeout=remaining,
    )
    missing = extraction_repair.targets(original, catalog, staging=staging)
    if not missing:
        return Result(original)
    try:
        eligible = await _preview(accept, original, original, deadline)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return Result(
            original,
            {"status": "preview_failed", "attempted": False, "failure": describe_failure(exc).code},
        )
    if not eligible:
        return Result(original, {"status": "invalid_initial_candidates", "attempted": False})
    return await _repair(
        llm,
        instructions,
        payload,
        catalog,
        original,
        missing,
        game_id=game_id,
        staging=staging,
        deadline=deadline,
        max_context=max_context,
        accept=accept,
        correction_policy=correction_policy,
    )


async def _repair(
    llm: Any,
    instructions: str,
    payload: str,
    catalog: Catalog,
    original: SharedItemExtraction,
    missing: dict[str, set[str]],
    *,
    game_id: str,
    staging: bool,
    deadline: float,
    max_context: int,
    accept: Callable[[ItemExtraction, ItemExtraction], Awaitable[bool]],
    correction_policy: correction_input.Policy | None = None,
) -> Result:
    attempted = False
    try:
        context = json.loads(payload)
        context["coverage_correction"] = extraction_repair.feedback(original, missing)
        domains = set().union(*missing.values())
        response_schema = extraction_repair.schema(catalog, domains=domains)
        system = instructions + extraction_repair.INSTRUCTIONS
        focused_system = (
            correction_policy.instructions(domains) + extraction_repair.INSTRUCTIONS
            if correction_policy
            else None
        )
        prepared = correction_input.prepare(
            llm,
            system,
            context,
            response_schema,
            max_context,
            focused_instructions=focused_system,
        )
        if prepared is None:
            return Result(original, {"status": "input_budget", "attempted": False})
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return Result(original, {"status": "deadline", "attempted": False})
        attempted = True
        additions = await asyncio.wait_for(
            llm.aexecute_complex_task(
                prepared.instructions,
                prepared.content,
                extraction_repair.Additions,
                llm.model,
                game_id=game_id,
                operation="narrated_items",
                phase="coverage_correction",
                response_schema=response_schema,
                single_attempt=True,
                max_input_chars=max_context,
            ),
            timeout=remaining,
        )
        additions = extraction_repair.Additions.model_validate(additions)
        corrected, audit = extraction_repair.merge(
            original, additions, missing, catalog, staging=staging
        )
        if corrected is not original and not await _preview(accept, corrected, original, deadline):
            return Result(original, {"status": "invalid_additions", "attempted": True})
        return Result(corrected, {**audit, "attempted": True, "focused_input": prepared.focused})
    except asyncio.CancelledError:
        raise
    except InputBudgetError as exc:
        return Result(
            original,
            {
                "status": "input_budget",
                "attempted": attempted,
                "input_chars": exc.measured,
                "limit": exc.limit,
            },
        )
    except Exception as exc:
        # The completed initial result is still independently validated and applied.
        return Result(
            original,
            {"status": "failed", "attempted": attempted, "failure": describe_failure(exc).code},
        )


async def _preview(
    accept: Callable[[ItemExtraction, ItemExtraction], Awaitable[bool]],
    candidate: ItemExtraction,
    original: ItemExtraction,
    deadline: float,
) -> bool:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError("State correction deadline expired.")
    return await asyncio.wait_for(accept(candidate, original), timeout=remaining)
