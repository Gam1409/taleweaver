"""Safe, actionable reconciliation failures without provider text or credentials."""

import json
from dataclasses import asdict, dataclass

from pydantic import ValidationError

from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError
from backend.engine.narrated_items.validation_details import details


@dataclass(frozen=True)
class ReconciliationFailure:
    code: str
    reason: str
    validation_fields: tuple[str, ...] = ()
    validation_details: tuple[dict[str, str], ...] = ()

    def payload(self) -> dict:
        return asdict(self)

    def message(self) -> str:
        fields = (
            f" Validation fields: {', '.join(dict.fromkeys(self.validation_fields))}."
            if self.validation_fields
            else ""
        )
        return (
            f"Item reconciliation failed: {self.reason}{fields} "
            "No item changes were applied by this check; the story was retained. "
            "Existing clothing can be inspected in Debug → Clothing."
        )


def describe_failure(exc: Exception) -> ReconciliationFailure:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and len(chain) < 5 and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    validation = next((error for error in chain if isinstance(error, ValidationError)), None)
    if validation is not None:
        rows = tuple(details(validation))
        return ReconciliationFailure(
            "invalid_schema",
            "the model returned invalid item or garment data.",
            tuple(row["field"] for row in rows),
            rows,
        )
    if any(isinstance(error, InferenceUncertainError) for error in chain):
        return ReconciliationFailure(
            "inference_uncertain",
            "the AI server may still be processing an earlier request. "
            "Check the Inference queue before retrying.",
        )
    if any(isinstance(error, (TimeoutError, InferenceQueueError)) for error in chain):
        return ReconciliationFailure(
            "timeout", "the item check timed out or could not enter the AI queue."
        )
    if any(isinstance(error, json.JSONDecodeError) for error in chain):
        return ReconciliationFailure("invalid_json", "the model returned unreadable item JSON.")
    return ReconciliationFailure(
        "unavailable", "the item check could not complete. See the server log for details."
    )
