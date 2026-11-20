"""Group complete structural diagnostics under existing bounded proposal edit paths."""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from backend.engine.chpm import proposal_edits

MAX_MESSAGE_CHARS = 600


@dataclass(frozen=True)
class Report:
    groups: list[dict]
    error_count: int
    missing: bool
    additional_count: int = 0


def _within(path: str, parent: str) -> bool:
    return path == parent or path.startswith(parent + "/")


def _cover(path: str, targets: set[str]) -> str:
    return min((target for target in targets if _within(path, target)), key=len)


def _targets(paths: set[str], allowed: set[str]) -> set[str]:
    independent = {_cover(path, paths) for path in paths}
    siblings = Counter(path.rpartition("/")[0] for path in independent)
    parents = {parent for parent, count in siblings.items() if count > 1 and parent in allowed}
    grouped = {
        path.rpartition("/")[0] if path.rpartition("/")[0] in parents else path
        for path in independent
    }
    return {_cover(path, grouped) for path in grouped}


def inspect(
    candidate: dict,
    schema: type[BaseModel],
    allowed_paths: list[str],
    *,
    additional_errors: list[dict] | tuple = (),
) -> Report | None:
    """None selects the existing full-response fallback rather than truncating issues."""
    errors: list[dict] = []
    try:
        schema.model_validate(deepcopy(candidate))
    except ValidationError as exc:
        errors = [
            dict(error)
            for error in exc.errors(include_input=False, include_url=False, include_context=False)
        ]
    errors.extend(additional_errors)
    if not errors:
        return Report([], 0, False)
    if len(errors) > proposal_edits.MAX_PATHS:
        return None
    allowed = set(allowed_paths)
    issues: dict[str, list[dict]] = {}
    for error in errors:
        path = proposal_edits.pointer(error["loc"])
        owners = [parent for parent in allowed if _within(path, parent)]
        if (
            not owners
            or len(path) > proposal_edits.MAX_PATH_LENGTH
            or len(error["msg"]) > MAX_MESSAGE_CHARS
        ):
            return None
        owner = max(owners, key=len)
        issues.setdefault(owner, []).append(
            {
                "path": path,
                "type": error["type"],
                "message": error["msg"],
                **({"category": error["category"]} if "category" in error else {}),
            }
        )
    targets = _targets(set(issues), allowed)
    if len(targets) > proposal_edits.MAX_EDITS:
        # Dense errors can still occupy only a few independent fields. Let the
        # model replace those fields once and keep every unaffected field intact.
        targets = {_cover(path, allowed) for path in targets}
    if len(targets) > proposal_edits.MAX_EDITS:
        return None
    grouped: dict[str, list[dict]] = {target: [] for target in sorted(targets)}
    for path, details in issues.items():
        grouped[_cover(path, targets)].extend(details)
    return Report(
        [{"path": path, "issues": details} for path, details in grouped.items()],
        len(errors),
        any(error["type"] == "missing" for error in errors),
        len(additional_errors),
    )
