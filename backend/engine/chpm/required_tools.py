"""Shared checks for a round that must produce an offered action call."""

from backend.core.llm_tool_turn import InvalidToolTurnError, ToolTurn


def names(tools: list[dict]) -> set[str]:
    offered = {tool["function"]["name"] for tool in tools}
    if not offered or "submit_decision" in offered:
        raise InvalidToolTurnError(
            "A required action round needs nonterminal tool declarations.",
            code="unavailable_function",
        )
    return offered


def check(turn: ToolTurn, offered: set[str]) -> None:
    # Irregular finish dispositions belong to the existing inference/finish checks.
    if turn.finish_reason not in (None, "stop", "tool_calls"):
        return
    if not turn.calls:
        raise InvalidToolTurnError(
            "The required action call is missing.", code="required_tool_missing"
        )
    if any(call.name not in offered for call in turn.calls):
        raise InvalidToolTurnError(
            "Choose only functions offered for this action.",
            code="unavailable_function",
            # A repair cannot reuse a parsed call ID from a rejected batch.
            call_ids=tuple(call.id for call in turn.calls if 0 < len(call.id) <= 128),
        )
