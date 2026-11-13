"""One shared proposal retry, preserving room for the remaining turn and prose review."""

from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from backend.core.state_rejection_trace import reject
from backend.engine.chpm import choice_grounds, inference, parallel_budget, proposal_repair
from backend.engine.chpm.core.errors import TransitionError
from backend.engine.chpm.errors import ProposalRejectedError
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import Settings, Usage

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")


async def request(
    manager: Any,
    settings: Settings,
    usage: Usage,
    instruction: str,
    payload: dict,
    schema: type[T],
    identifiers: dict,
    accept: Callable[[T], R],
) -> R:
    phase = "proposal"
    while True:
        try:
            raw = await inference.request(
                manager,
                settings,
                usage,
                instruction,
                payload,
                schema,
                phase,
                identifiers=identifiers,
            )
        except inference.InvalidResponseError as exc:
            reject(
                "emotion",
                "chpm.proposal_invalid",
                str(exc),
                proposal=exc.candidate,
                context=payload,
                phase=phase,
                identifiers=identifiers,
                schema=schema.__name__,
            )
            feedback = str(exc)
            candidate = exc.candidate
            hint = choice_grounds.repair_hint(candidate) if issubclass(schema, Draft) else ""
            if hint:
                feedback = f"{feedback}; {hint}"[:600]
        except inference.OutputBudgetError as exc:
            reject(
                "emotion",
                "chpm.proposal_output_budget",
                str(exc),
                context=payload,
                phase=phase,
                identifiers=identifiers,
                usage=usage,
            )
            raise ProposalRejectedError(str(exc)) from exc
        else:
            candidate = raw.model_dump(mode="json")
            try:
                return accept(raw)
            except (ChpmError, TransitionError, ValidationError) as exc:
                reject(
                    "emotion",
                    "chpm.proposal_invalid",
                    str(exc),
                    proposal=candidate,
                    context=payload,
                    phase=phase,
                    identifiers=identifiers,
                    validation_errors=exc.errors(include_url=False)
                    if isinstance(exc, ValidationError)
                    else None,
                )
                feedback = inference.validation_feedback(exc)
        # This is a two-entry diagnostic window, not canonical story history.
        usage.proposal_feedback = [*usage.proposal_feedback, feedback[:600]][-2:]
        if phase == "proposal_repair" or usage.proposal_repairs:
            raise ProposalRejectedError(
                "CHPM proposal remains invalid; no decision applied. " + feedback
            )
        turn = getattr(manager, "_chpm_turn", None)
        remaining = max(0, len(turn.names) - len(turn.decisions) - 1) if turn else 0
        reserve = parallel_budget.remaining(remaining * (1 + settings.agent_steps)) + (
            3 if settings.mode == "live" else 0
        )
        if usage.calls + 1 + reserve > settings.max_calls_per_turn:
            raise ProposalRejectedError(
                "CHPM proposal retry has no reserved request budget. " + feedback
            )
        payload = proposal_repair.payload_for(
            payload,
            schema,
            feedback,
            candidate,
            instruction=instruction,
            identifiers=identifiers,
            limit=settings.max_input_chars,
        )
        prompt, content = inference.compose(instruction, payload, schema, identifiers)
        if len(prompt) + len(content) > settings.max_input_chars:
            raise ProposalRejectedError(
                "CHPM proposal retry cannot fit its input budget. " + feedback
            )
        usage.proposal_repairs += 1
        phase = "proposal_repair"
