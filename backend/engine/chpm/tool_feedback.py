"""Static recovery hints for unavailable observer-local handles; no capability lookup."""

_HINTS = {
    ("visible_clothing", "unavailable_actor"): (
        "Use visible_clothing only for a listed visible_clothing_actors NPC. "
        "For the player use inspect_entity(argument='@player'); for yourself use "
        "inspect_self or inspect_entity with observer_id. Unavailable does not mean undressed."
    ),
    ("find_entity", "unavailable_view"): (
        "The current observer view is unavailable or stale. Do not infer absence or create a replacement."
    ),
    ("inspect_scene", "unavailable_view"): (
        "The current scene view is unavailable or stale. Do not infer an empty room or an open route."
    ),
    ("inspect_entity", "unavailable_entity"): (
        "Use an exact accessible ID from observable_entities or the current host context. "
        "The view may be unavailable or stale. This does not prove absence and does not "
        "authorize creating a replacement item."
    ),
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
