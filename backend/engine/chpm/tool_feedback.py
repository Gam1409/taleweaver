"""Static recovery hints for unavailable observer-local handles; no capability lookup."""

_HINTS = {
    ("read_belief_basis", "unavailable_belief"): (
        "Use a belief_id returned by inspect_beliefs in this investigation. "
        "Notebook text is not a belief handle; inspect your own beliefs first if needed."
    ),
    ("read_memory", "unavailable_source"): (
        "Use a memory_id returned by search_memory in this investigation. "
        "Search first if needed; notebook text is not a memory handle."
    ),
}


def for_model(tool: str, result: dict) -> dict:
    """Enrich only model feedback, preserving the original status and domain result."""
    status = result.get("status")
    hint = _HINTS.get((tool, status)) if isinstance(status, str) else None
    if hint is None:
        return result
    field = "corrective_hint" if isinstance(result.get("message"), str) else "message"
    return {**result, field: hint}
