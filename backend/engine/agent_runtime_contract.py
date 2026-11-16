"""Inspect portable configuration without activating engines or importing resources."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel, ValidationError

from backend.schemas.agent_runtime import AgentRuntime, NpcAgentRuntime

KNOWN_FEATURES = frozenset(
    {
        "npc.autonomy.v1",
        "psychology.authored.v1",
        "rag.observer.v1",
        "living_world.v1",
        "living_world.catch_up.v1",
        "library.remote.v1",
    }
)


@dataclass(frozen=True)
class Inspection:
    status: str
    active_features: frozenset[str] = frozenset()
    missing_required: frozenset[str] = frozenset()
    ignored_optional: frozenset[str] = frozenset()
    unknown_fields: tuple[str, ...] = ()
    error_paths: tuple[str, ...] = ()
    config: AgentRuntime | None = None


def _unknown(value: Any, path: str = "agent_runtime") -> list[str]:
    if isinstance(value, BaseModel):
        own = [f"{path}.{key}" for key in (value.model_extra or {})]
        nested = [
            entry
            for key in type(value).model_fields
            for entry in _unknown(getattr(value, key), f"{path}.{key}")
        ]
        return own + nested
    if isinstance(value, list):
        return [entry for i, item in enumerate(value) for entry in _unknown(item, f"{path}[{i}]")]
    return []


def known_projection(value: Any) -> Any:
    """Execution adapters use known fields only; export always uses the original JSON."""
    if isinstance(value, BaseModel):
        return {key: known_projection(getattr(value, key)) for key in type(value).model_fields}
    if isinstance(value, list):
        return [known_projection(item) for item in value]
    return value


def inspect_runtime(raw: Any, supported: frozenset[str] = frozenset()) -> Inspection:
    """Declared features are versioned IDs; no host support is assumed by default."""
    if raw is None:
        return Inspection("absent")
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int:
        return Inspection("invalid", error_paths=("schema_version",))
    if raw["schema_version"] != 1:
        return Inspection("unsupported_version", error_paths=("schema_version",))
    try:
        config = AgentRuntime.model_validate(raw)
    except ValidationError as exc:
        paths = tuple(".".join(map(str, item["loc"])) for item in exc.errors())
        return Inspection("invalid", error_paths=paths)
    available = supported & KNOWN_FEATURES
    missing = frozenset(config.required_features) - available
    ignored = frozenset(config.optional_features) - available
    active = frozenset(config.requested_features()) & available
    # Dependent capabilities cannot run without their parent.
    if "living_world.v1" not in active:
        active -= {"living_world.catch_up.v1"}
    if "rag.observer.v1" not in active:
        active -= {"library.remote.v1"}
    return Inspection(
        "missing_required" if missing else "ready",
        frozenset() if missing else active,
        missing,
        ignored,
        tuple(_unknown(config)),
        config=config,
    )


def validate_npcs(manifest: Mapping[str, Any]) -> dict[str, NpcAgentRuntime]:
    """Validate static seeds and references independently of database row keys."""
    npcs = manifest.get("npcs", [])
    if not isinstance(npcs, list) or any(
        not isinstance(npc, dict) or not isinstance(npc.get("id"), str) for npc in npcs
    ):
        raise ValueError("NPCs require string IDs.")
    ids = {npc["id"] for npc in npcs}
    if len(ids) != len(npcs):
        raise ValueError("NPC IDs must be unique.")
    parsed = {}
    for npc in npcs:
        metadata = npc.get("metadata_json") or {}
        if not isinstance(metadata, dict):
            raise ValueError("NPC metadata must be an object.")
        raw = metadata.get("agent_runtime")
        if raw is None:
            continue
        value = NpcAgentRuntime.model_validate(raw)
        if any(
            seed.target_id not in ids | {"PROTAGONIST"}
            for seed in value.initial_state.relationships
        ):
            raise ValueError("Unknown relationship target.")
        parsed[npc["id"]] = value
    return parsed


def inspect_manifest(manifest: dict, supported: frozenset[str] = frozenset()) -> Inspection:
    """An activation preflight, separate from opaque transport and template storage."""
    extensions = manifest.get("extensions", {})
    if not isinstance(extensions, dict):
        return Inspection("invalid", error_paths=("extensions",))
    result = inspect_runtime(extensions.get("agent_runtime"), supported)
    if result.status not in {"absent", "ready"}:
        return result
    try:
        npcs = validate_npcs(manifest)
    except (ValidationError, ValueError, TypeError):
        return replace(result, status="invalid", active_features=frozenset(), error_paths=("npcs",))
    if npcs and result.status == "absent":
        return replace(result, status="invalid", error_paths=("extensions.agent_runtime",))
    unknown = tuple(
        entry
        for actor, npc in npcs.items()
        for entry in _unknown(npc, f"npcs.{actor}.agent_runtime")
    )
    return replace(result, unknown_fields=result.unknown_fields + unknown)
