"""Preflight validates references, field types and sandbox syntax without a model call."""

import re
from collections.abc import Iterator

from backend.engine.blueprint.field_specs import KEY_TABLES, REF_FIELDS, REF_LIST_FIELDS
from backend.engine.blueprint.models import Blueprint, BlueprintBlock
from backend.engine.scripting.sandbox import SafeAstInterpreter

MAX_BLUEPRINT_CHARS = 20_000
MAX_BLOCKS = 256
_MENTION = re.compile(r"@([A-Z][A-Z0-9_]+)")


def iter_blocks(blueprint: Blueprint) -> Iterator[BlueprintBlock]:
    for block in blueprint.blocks:
        yield block
        yield from block.children


def _check_fields(blueprint: Blueprint, block: BlueprintBlock, references: dict[str, int]) -> None:
    roles = {spec.target: spec.role for spec in KEY_TABLES.get(block.kind, {}).values()}
    for key, value in block.fields.items():
        messages = []
        if roles.get(key) == "script":
            messages = SafeAstInterpreter.check_syntax(str(value.value))
        elif roles.get(key) == "expr":
            messages = SafeAstInterpreter.check_expression_syntax(str(value.value))
        for message in messages:
            blueprint.add_issue(value.line, f"{block.kind} '{block.ref}' {key}: {message}")
        if key in REF_FIELDS and value.value:
            references.setdefault(str(value.value), value.line)
        if key in REF_LIST_FIELDS and isinstance(value.value, list):
            for ref in value.value:
                if isinstance(ref, str) and ref:
                    references.setdefault(ref, value.line)


def validate_blueprint(blueprint: Blueprint) -> list[str]:
    seen: dict[tuple[str, str], int] = {}
    references: dict[str, int] = {}
    blocks = list(iter_blocks(blueprint))
    if len(blocks) > MAX_BLOCKS:
        blueprint.add_issue(1, f"At most {MAX_BLOCKS} blueprint blocks are allowed.")
    for block in blocks:
        if block.kind not in KEY_TABLES:
            blueprint.add_issue(
                block.line, f"'{block.kind}' blocks are not supported by this engine."
            )
            continue
        key = ("entity" if block.kind in {"scene", "npc", "item"} else block.kind, block.ref)
        if key in seen:
            blueprint.add_issue(
                block.line, f"Duplicate ID '{block.ref}' (first on line {seen[key]})."
            )
        seen[key] = block.line
        for child in block.children:
            if child.kind != "ability":
                blueprint.add_issue(
                    child.line,
                    f"Nested '{child.kind}' is not supported; use a top-level script with an explicit target.",
                )
        _check_fields(blueprint, block, references)
        for mention in _MENTION.findall(block.description):
            references.setdefault(mention, block.line)
        if block.kind == "script" and not block.fields.get("code"):
            blueprint.add_issue(block.line, f"Script '{block.ref}' requires code.")
    missing = sorted(set(references) - blueprint.declared_ids())
    for ref in missing:
        blueprint.add_issue(
            references[ref],
            f"'{ref}' is referenced but not declared; generation must create it.",
            "warning",
        )
    return missing
