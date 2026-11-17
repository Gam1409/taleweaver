"""Small family compatibility policies for the existing native and portable ports."""

from dataclasses import dataclass
from typing import Any, Literal

from backend.engine.chpm.errors import RecoverableChpmError

ToolProfile = Literal["auto", "anthropic", "openai", "mistral", "gemma", "deepseek", "qwen"]


@dataclass(frozen=True)
class Profile:
    label: str
    prefer_json: bool = False
    note: str = "Uses the existing native adapter preflight and JSON fallback."


CATALOG: dict[ToolProfile, Profile] = {
    "auto": Profile("Auto", note="Preserves the existing configured tool selection."),
    "anthropic": Profile("Anthropic"),
    "openai": Profile("OpenAI"),
    "mistral": Profile("Mistral"),
    "gemma": Profile(
        "Gemma",
        prefer_json=True,
        note="Prefers JSON because current native templates cannot render the full tool schemas.",
    ),
    "deepseek": Profile("DeepSeek"),
    "qwen": Profile(
        "Qwen",
        prefer_json=True,
        note="Prefers JSON because native argument typing depends on the runtime and parser version.",
    ),
}
_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}
_COMPOSITION = {
    "$ref",
    "$dynamicRef",
    "$recursiveRef",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
    "dependentSchemas",
    "patternProperties",
    "prefixItems",
    "contains",
    "unevaluatedProperties",
    "unevaluatedItems",
}


def prefers_json(profile: ToolProfile, protocol: str) -> bool:
    """Choose once before dispatch; a family is not a runtime or model-name detector."""
    return protocol == "json" or (protocol == "auto" and CATALOG[profile].prefer_json)


def validate_native(profile: ToolProfile, tools: list[dict]) -> None:
    """Reject known declaration-shape loss without changing schemas or reserving a call."""
    policy = CATALOG[profile]
    if not policy.prefer_json:
        return
    for tool in tools:
        issue = _schema_issue(tool.get("function", {}).get("parameters"))
        if issue:
            raise RecoverableChpmError(
                f"The {policy.label} profile cannot safely represent {issue} in these native "
                "tool declarations. Keep this profile and set tool compatibility to "
                "Automatic or JSON compatibility. Native support also "
                "depends on the configured runtime and template. No request was sent."
            )


def _schema_issue(node: Any) -> str | None:
    if not isinstance(node, dict) or _COMPOSITION.intersection(node):
        return "schema references or composition"
    kind = node.get("type")
    if not isinstance(kind, str) or kind not in _TYPES:
        return "untyped or union-valued inputs"
    if kind == "object" and node.get("additionalProperties") is not False:
        return "open JSON dictionaries"
    for child in _children(node):
        issue = _schema_issue(child)
        if issue:
            return issue
    return None


def _children(node: dict) -> list[Any]:
    """Walk schema locations only; const/enum/default/examples contain literal data."""
    if node["type"] == "array":
        return [node.get("items")]
    if node["type"] != "object":
        return []
    properties = node.get("properties", {})
    return list(properties.values()) if isinstance(properties, dict) else [None]
