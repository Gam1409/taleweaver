"""Structured world authoring adapted from jschm42/taleweaver 012599eff (MIT)."""

from dataclasses import dataclass

from backend.engine.blueprint.merge import BlueprintMergeError, apply_blueprint
from backend.engine.blueprint.models import Blueprint, BlueprintIssue
from backend.engine.blueprint.parser import has_blueprint_tags, parse_blueprint
from backend.engine.blueprint.prompt import render_blueprint_prompt
from backend.engine.blueprint.validator import MAX_BLUEPRINT_CHARS, validate_blueprint


class BlueprintError(ValueError):
    def __init__(self, issues: list[BlueprintIssue]):
        self.issues = issues
        super().__init__(
            "Blueprint errors: "
            + "; ".join(f"line {issue.line}: {issue.message}" for issue in issues[:12])
        )


@dataclass
class PreparedBlueprint:
    blueprint: Blueprint
    missing_ids: list[str]

    @property
    def premise(self) -> str:
        return self.blueprint.premise

    def prompt_section(self, generation_strictness: str) -> str:
        return render_blueprint_prompt(self.blueprint, self.missing_ids, generation_strictness)


def analyze_blueprint(text: str) -> tuple[Blueprint, list[str]]:
    if len(text) > MAX_BLUEPRINT_CHARS:
        raise BlueprintError(
            [BlueprintIssue(1, f"Story idea exceeds {MAX_BLUEPRINT_CHARS} characters.")]
        )
    blueprint = parse_blueprint(text)
    return blueprint, validate_blueprint(blueprint)


def prepare_blueprint(text: str) -> PreparedBlueprint | None:
    if not has_blueprint_tags(text):
        return None
    blueprint, missing = analyze_blueprint(text)
    if blueprint.errors:
        raise BlueprintError(blueprint.errors)
    return PreparedBlueprint(blueprint, missing)


__all__ = [
    "BlueprintError",
    "BlueprintMergeError",
    "analyze_blueprint",
    "apply_blueprint",
    "has_blueprint_tags",
    "prepare_blueprint",
]
