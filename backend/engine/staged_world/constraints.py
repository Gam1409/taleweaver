"""Check generation switches and requested sizes before accepting a world plan."""

from backend.core.game_modes import mode_policy

FLAGS = {
    "quests": "quest_generation_enabled",
    "awards": "award_generation_enabled",
    "scripts": "scripts_generation_enabled",
    "containers": "container_generation_enabled",
    "text_logs": "text_log_generation_enabled",
}


def validate_constraints(plan: dict, metadata: dict, mode: str | None) -> None:
    vn = mode_policy(mode).vn
    if vn and any(plan[k] for k in ("sequences", "quests", "awards", "scripts")):
        raise ValueError("VN plans must leave sequences, quests, awards and scripts empty.")
    if any(not row.get("item_type") for row in plan["objects"]):
        raise ValueError("Every object seed needs an item_type.")
    counts = {
        kind: len(plan[kind]) for kind in ("scenes", "sequences", "quests", "awards", "scripts")
    }
    counts.update(
        items=len(plan["objects"]),
        containers=sum(row.get("item_type") == "CONTAINER" for row in plan["objects"]),
        text_logs=sum(row.get("item_type") == "READABLE" for row in plan["objects"]),
    )
    for kind, count in counts.items():
        if vn and kind in {"sequences", "quests", "awards", "scripts"}:
            continue
        enabled = metadata.get(FLAGS.get(kind)) is not False
        _check_count(kind, count, enabled, metadata)


def _check_count(kind: str, count: int, enabled: bool, metadata: dict) -> None:
    if not enabled:
        if count:
            raise ValueError(f"{kind} are disabled and must be empty.")
        return
    minimum, maximum = metadata.get(f"min_{kind}"), metadata.get(f"max_{kind}")
    if minimum is not None and count < minimum:
        raise ValueError(f"Plan needs at least {minimum} {kind}.")
    if maximum is not None and count > maximum:
        raise ValueError(f"Plan allows at most {maximum} {kind}.")
