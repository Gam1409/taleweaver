"""Check author blueprints against actual mode and generation switches before spending tokens."""

from typing import Any

from backend.core.game_modes import mode_policy
from backend.engine.blueprint import BlueprintError, PreparedBlueprint, prepare_blueprint
from backend.engine.blueprint.field_specs import KEY_TABLES
from backend.engine.blueprint.validator import iter_blocks

_FLAGS = {
    "script": "scripts_generation_enabled",
    "sidequest": "quest_generation_enabled",
    "award": "award_generation_enabled",
}


def prepare_generation_blueprint(text: str, options: dict[str, Any]) -> PreparedBlueprint | None:
    prepared = prepare_blueprint(text)
    if prepared is None:
        return None
    blueprint = prepared.blueprint
    if _legacy_vn_outline(blueprint, options):
        return None
    for block in iter_blocks(blueprint):
        _block_options(blueprint, block, options)
    counts = {
        "scenes": len(blueprint.of_kind("scene")),
        "items": len(blueprint.of_kind("item")),
        "sequences": len(blueprint.of_kind("sequence")),
    }
    for category, count in counts.items():
        maximum = options.get(f"max_{category}")
        if maximum is not None and count > maximum:
            blueprint.add_issue(
                1, f"Blueprint declares {count} {category}; configured maximum is {maximum}."
            )
    if blueprint.errors:
        raise BlueprintError(blueprint.errors)
    return prepared


def _legacy_vn_outline(blueprint: Any, options: dict[str, Any]) -> bool:
    """Legacy prose-only chapters remain optional VN themes, as before this port."""
    return mode_policy(options.get("rule_enforcement_mode")).vn and all(
        block.kind == "sequence" and not block.children and set(block.fields) <= {"title"}
        for block in blueprint.blocks
    )


def _item_options(blueprint: Any, block: Any, options: dict[str, Any]) -> None:
    fixed = block.fixed()
    item_type = fixed.get("item_type")
    flags = {"CONTAINER": "container_generation_enabled", "READABLE": "text_log_generation_enabled"}
    if item_type in flags and options.get(flags[item_type]) is False:
        blueprint.add_issue(
            block.line, f"{item_type} items are disabled in the generation settings."
        )
    if len(fixed.get("text_log_content") or "") > 500:
        blueprint.add_issue(
            block.line, "Readable text must fit the engine's 500-character storage limit."
        )


def _block_options(blueprint: Any, block: Any, options: dict[str, Any]) -> None:
    policy = mode_policy(options.get("rule_enforcement_mode"))
    flag = _FLAGS.get(block.kind)
    if flag and options.get(flag) is False:
        blueprint.add_issue(block.line, f"Enable {flag.replace('_', ' ')} to include this block.")
    if policy.vn and block.kind in {"sequence", "script", "sidequest", "award", "ability"}:
        blueprint.add_issue(
            block.line,
            f"VN mode has no mechanical {block.kind} blocks; use scenes, character goals and plot for its outline.",
        )
    fixed = block.fixed()
    roles = {spec.target: spec.role for spec in KEY_TABLES[block.kind].values()}
    if options.get("scripts_generation_enabled") is False and any(
        roles.get(k) == "script" and v for k, v in fixed.items()
    ):
        blueprint.add_issue(block.line, "Authored scripts are disabled in the generation settings.")
    if block.kind == "item":
        _item_options(blueprint, block, options)
    key = {"award": "key", "sequence": "order"}.get(block.kind, "id")
    if key in fixed and str(fixed[key]).upper() != block.ref:
        blueprint.add_issue(
            block.line, f"Set {key} in the block header; it must match '{block.ref}'."
        )


def prepare_generation_brief(
    text: str, sequences: list[dict] | None, options: dict[str, Any]
) -> tuple[str, list[dict] | None, PreparedBlueprint | None]:
    """Keep the full blueprint text for persistence and the legacy outline path unchanged."""
    from backend.engine.world_manifest_text import _extract_sequences_from_prompt

    prepared = prepare_generation_blueprint(text, options)
    if prepared or sequences or not text:
        return text, sequences, prepared
    cleaned, extracted = _extract_sequences_from_prompt(text)
    return (cleaned, extracted, None) if extracted else (text, sequences, None)
