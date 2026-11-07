"""Safe, actionable reconciliation failures without provider text or credentials."""

import json
from dataclasses import asdict, dataclass

from pydantic import ValidationError

from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError


@dataclass(frozen=True)
class ReconciliationFailure:
    code: str
    reason: str
    validation_fields: tuple[str, ...] = ()

    def payload(self) -> dict:
        return asdict(self)

    def message(self) -> str:
        return (
            f"Item reconciliation failed: {self.reason} "
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
        allowed = {
            "actions",
            "item_id",
            "new_item",
            "source_owner",
            "destination_owner",
            "disposition",
            "evidence",
            "basis",
            "name",
            "description",
            "kind",
            "clothing",
            "wearable_slots",
            "category",
            "layer",
            "coverage",
            "opaque",
            "underwear",
        }
        fields = tuple(
            ".".join(str(part) for part in error["loc"] if part in allowed or type(part) is int)
            for error in validation.errors(include_input=False, include_context=False)[:5]
        )
        return ReconciliationFailure(
            "invalid_schema", "the model returned invalid item or garment data.", fields
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
