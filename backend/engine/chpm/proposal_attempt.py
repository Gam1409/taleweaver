"""One shared proposal retry, preserving room for the remaining turn and prose review."""

from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from backend.engine.chpm import inference
from backend.engine.chpm.core.errors import TransitionError
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.kernel import ChpmError
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
            feedback = str(exc)
        else:
            try:
                return accept(raw)
            except (ChpmError, TransitionError, ValidationError) as exc:
                feedback = inference.validation_feedback(exc)
        # This is a two-entry diagnostic window, not canonical story history.
        usage.proposal_feedback = [*usage.proposal_feedback, feedback[:600]][-2:]
        if phase == "proposal_repair" or usage.proposal_repairs:
            raise RecoverableChpmError(
                "CHPM proposal remains invalid; no decision applied. " + feedback
            )
        turn = getattr(manager, "_chpm_turn", None)
        remaining = max(0, len(turn.names) - len(turn.decisions) - 1) if turn else 0
        reserve = remaining * (1 + settings.agent_steps) + (3 if settings.mode == "live" else 0)
        if usage.calls + 1 + reserve > settings.max_calls_per_turn:
            raise RecoverableChpmError(
                "CHPM proposal retry has no reserved request budget. " + feedback
            )
        payload = {
            **payload,
            "proposal_feedback": {
                "error": feedback,
                "required_top_level_fields": [
                    key for key, field in schema.model_fields.items() if field.is_required()
                ],
                "instruction": "Return the complete corrected object with all required fields. Keep explanations to one short clause below their character caps. Preserve exact citations, conditions and identity; do not invent facts or replace fields with obsolete appraisal.",
            },
        }
        prompt, content = inference.compose(instruction, payload, schema, identifiers)
        if len(prompt) + len(content) > settings.max_input_chars:
            raise RecoverableChpmError(
                "CHPM proposal retry cannot fit its input budget. " + feedback
            )
        usage.proposal_repairs += 1
        phase = "proposal_repair"
