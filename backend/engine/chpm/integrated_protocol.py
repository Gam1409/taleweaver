"""Workflow-owned protocol feedback; no execution, hidden retries or added call budget."""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.engine import turn_controls
from backend.engine.chpm import agent_native, inference, json_contract
from backend.engine.chpm.agent_limits import MAX_TOOL_ARGUMENT_CHARS
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.notebook.codec import preflight
from backend.engine.chpm.schema import Settings, Usage

logger = logging.getLogger(__name__)
FINAL = "submit_decision"
HINTS = {
    "invalid_json": (
        "Return one complete finite JSON object in the offered function-call format, "
        "without commentary, duplicate keys or trailing text. No operation was parsed."
    ),
    "missing_requests": (
        "The portable response is missing its requests array. Add one request named "
        "submit_decision and put the complete proposal inside its arguments object. "
        "Neither choice nor candidates are top-level response fields."
    ),
    "unexpected_fields": (
        "The portable response has extra top-level fields. Keep only requests and optional "
        "purpose. Put function inputs inside arguments; do not add copied host metadata."
    ),
    "too_many_requests": (
        "At most two function calls are allowed per response. submit_decision must be alone. "
        "Action and memory calls share that limit. Split nonfinal calls across available "
        "rounds and read their results before submitting a decision alone."
    ),
    "invalid_structure": (
        "Return only the offered function-call format. In portable JSON use an object "
        "with only requests, containing name/arguments objects. Put the complete proposal "
        "inside submit_decision.arguments, without commentary or extra top-level fields."
    ),
    "mixed_submission": (
        "Submit a decision separately from all action and memory functions. While nonfinal "
        "functions are still offered, send at most two and read their results before "
        "submitting alone. At final-only stage, submit a grounded decision without claiming "
        "unperformed actions."
    ),
    "invalid_call_envelope": (
        "Use at most two calls with distinct valid IDs and bounded arguments. "
        "Do not reuse a previous call ID. Submit a decision separately from all other functions."
    ),
    "unavailable_function": (
        "The response requested an unavailable function. Use only the currently offered "
        "function names; at zero remaining rounds only submit_decision is available."
    ),
    "missing_submission": (
        "No final submission was provided. Call submit_decision alone with the complete "
        "proposal in arguments. Do not return an empty requests array or a readiness message."
    ),
}


class ProtocolError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(HINTS[code])
        self.code = code


async def read(
    manager: Any,
    settings: Settings,
    usage: Usage,
    messages: list[dict],
    offered: list[dict],
    *,
    seen_ids: set[str],
    **kwargs: Any,
) -> Any:
    """Validate a whole response before any operation in it can execute."""
    try:
        turn = await inference.tool_request(manager, settings, usage, messages, offered, **kwargs)
    except inference.ToolEnvelopeError as exc:
        raise ProtocolError(exc.code if exc.code in HINTS else "invalid_structure") from exc
    if not agent_native._valid_envelope(turn.calls, seen_ids):
        raise ProtocolError("invalid_call_envelope")
    finals = [call for call in turn.calls if call.name == FINAL]
    if finals and len(turn.calls) != 1:
        raise ProtocolError("mixed_submission")
    if not turn.calls and not _proposal_content(turn.assistant_message.get("content")):
        raise ProtocolError("missing_submission")
    names = {item["function"]["name"] for item in offered}
    if any(call.name not in names for call in turn.calls):
        raise ProtocolError("unavailable_function")
    return turn


def _proposal_content(raw: Any) -> bool:
    if not isinstance(raw, str) or len(raw) > MAX_TOOL_ARGUMENT_CHARS:
        return False
    try:
        preflight(raw, max_transport_bytes=MAX_TOOL_ARGUMENT_CHARS * 4)
        candidate = json_contract.decode(raw)
        json.dumps(candidate, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, OverflowError):
        return False
    return {"candidates", "choice"} <= candidate.keys()


@dataclass
class Recovery:
    used: bool = False

    def explain(
        self,
        error: ProtocolError,
        history: list[dict],
        audit: list[dict],
        *,
        remaining: int,
        protocol: str,
        captured: Mapping | None = None,
    ) -> None:
        if self.used or remaining <= 0:
            raise RecoverableChpmError(str(error)) from error
        self.used = True
        message = (
            str(error)
            + " Rejected operations did not run; do not repeat earlier successful operations."
        )
        control = (
            turn_controls.operation(captured, "tool_response").model_dump(exclude_none=True)
            if captured is not None
            else {}
        )
        history.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "host_protocol_feedback": {
                            **{
                                key: control[key]
                                for key in ("attempt_id", "operation_id")
                                if key in control
                            },
                            "code": error.code,
                            "message": message,
                            "operations_applied": False,
                        }
                    }
                ),
            }
        )
        audit.append(
            {
                **control,
                "purpose": "Host protocol feedback",
                "purpose_truncated": False,
                "protocol": protocol,
                "requests": [],
                "results": [],
                "stop": "invalid_envelope",
                "error_type": error.code,
            }
        )
        logger.warning(
            "CHPM tool response rejected; bounded correction offered: code=%s", error.code
        )
