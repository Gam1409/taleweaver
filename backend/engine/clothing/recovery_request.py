"""One bounded retry for malformed recovery output, without weakening validation."""

from typing import TypeVar

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from backend.core.llm_router import GameMasterLLM

T = TypeVar("T", bound=BaseModel)

# Only fixed application messages may appear in feedback; arbitrary validator text stays private.
_VALIDATOR_HINTS = {
    "Use an existing ID or a new item, never both.": "supply exactly one of item_id and new_item",
    "Clothing requires garment metadata and slots.": "new clothing requires metadata and wearable_slots",
    "Ordinary items cannot carry clothing metadata.": "ordinary items cannot include clothing metadata",
    "Coverage regions must be unique.": "coverage contains duplicate regions",
}


def _issue_reason(issue: ErrorDetails) -> str:
    hint = _VALIDATOR_HINTS.get(str((issue.get("ctx") or {}).get("error", "")))
    return f"{issue['type']} ({hint})" if hint else issue["type"]


def validation_failure(error: ValueError) -> ValidationError | None:
    if isinstance(error, ValidationError):
        return error
    return error.__cause__ if isinstance(error.__cause__, ValidationError) else None


def schema_issues(error: ValidationError) -> str:
    # Do not include model output, Pydantic input values or arbitrary validator messages.
    return "; ".join(
        f"{'.'.join(str(part)[:80] for part in issue['loc']) or 'root'}: {_issue_reason(issue)}"
        for issue in error.errors(include_input=False, include_context=True, include_url=False)[:8]
    )


async def _request(
    llm: GameMasterLLM, prompt: str, payload: str, model: type[T], session_id: str, phase: str
) -> T:
    result = await llm.aexecute_complex_task(
        prompt,
        payload,
        model,
        llm.model,
        game_id=session_id,
        operation="wardrobe_recovery",
        phase=phase,
    )
    return model.model_validate(result.model_dump() if isinstance(result, BaseModel) else result)


async def request_proposal(
    llm: GameMasterLLM, prompt: str, payload: str, model: type[T], session_id: str
) -> T:
    try:
        return await _request(llm, prompt, payload, model, session_id, "preview")
    except ValueError as exc:
        failure = validation_failure(exc)
        if failure is None:
            raise
        issues = schema_issues(failure)
    feedback = (
        "\nYour previous response failed schema validation at: " + issues + ".\n"
        "Re-extract from the same evidence and return a complete valid proposal. "
        "Do not invent facts to fill fields. Entries contain source_message_id and action. "
        "Each action uses exactly one of item_id or new_item (the other is null). "
        "New clothing requires kind=clothing, garment metadata and nonempty wearable_slots. "
        "Use only schema enums, integer layers 0–4 and JSON booleans. "
        "Keep uncovered_regions and placement_evidence on the entry, not inside action."
    )
    try:
        return await _request(llm, prompt + feedback, payload, model, session_id, "schema_retry")
    except ValueError as exc:
        failure = validation_failure(exc)
        if failure is None:
            raise
        raise ValueError(
            f"Recovery schema still invalid after one retry: {schema_issues(failure)}"
        ) from exc
