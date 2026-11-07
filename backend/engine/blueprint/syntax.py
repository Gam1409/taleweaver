"""Upstream blueprint tag grammar, separated from parser state (MIT, 012599eff)."""

import re

from backend.engine.blueprint.field_specs import normalize_key
from backend.engine.blueprint.markdown import match_markdown_heading_tag

MAX_SEQUENCES = 15

_TAG_RE = re.compile(
    r"^(\s*)(?:(#{1,6})\s+|[-*]\s+)?\[\s*([A-Za-z][A-Za-z_ ]*?)\s*(?::\s*([^\]]*))?\]\s*(.*)$"
)
_KEY_RE = re.compile(
    r"^(\s*)(?:[-*]\s+)?(?:\*\*|__|`)?([A-Za-z][A-Za-z0-9_ \-]{0,40}?)(?:\*\*|__|`)?\s*:\s*(.*)$"
)
_TRAILING_ID_RE = re.compile(r"^(.*?)\s*\(([A-Za-z][A-Za-z0-9_]*)\)\s*$")
_EXIT_REF_RE = re.compile(r"^\s*([^<>\-]+?)\s*(<->|->)\s*([^<>\-]+?)\s*$")

# tag word -> (block kind, preset item_type)
_KIND_ALIASES: dict[str, tuple[str, str]] = {
    "world": ("world", ""),
    "protagonist": ("protagonist", ""),
    "player": ("protagonist", ""),
    "scene": ("scene", ""),
    "location": ("scene", ""),
    "exit": ("exit", ""),
    "path": ("exit", ""),
    "npc": ("npc", ""),
    "character": ("npc", ""),
    "item": ("item", ""),
    "object": ("item", ""),
    "readable": ("item", "READABLE"),
    "container": ("item", "CONTAINER"),
    "switch": ("item", "SWITCH"),
    "containerswitch": ("item", "CONTAINER_SWITCH"),
    "container_switch": ("item", "CONTAINER_SWITCH"),
    "mechanism": ("item", "SWITCH"),
    "weapon": ("item", "WEAPON"),
    "recipe": ("item", "CONSTRUCTABLE"),
    "sequence": ("sequence", ""),
    "chapter": ("sequence", ""),
    "rule": ("rule", ""),
    "soft_rule": ("rule", ""),
    "script": ("script", ""),
    "sidequest": ("sidequest", ""),
    "quest": ("sidequest", ""),
    "award": ("award", ""),
    "ability": ("ability", ""),
    "talent": ("talent", ""),
}
_NAME_FIELDS = {
    "protagonist": "name",
    "scene": "name",
    "npc": "name",
    "item": "name",
    "sequence": "title",
    "sidequest": "title",
    "award": "title",
    "script": "name",
    "ability": "name",
    "talent": "name",
    "rule": "condition",
    "exit": "label",
}
_SINGLETON_KINDS = {"world", "protagonist"}
# Child tags of an entity (abilities, talents) or of the latest sequence (rules).
_ENTITY_CHILD_KINDS = {"ability", "talent"}
_CHILD_KINDS = {"rule", *_ENTITY_CHILD_KINDS}
_INTRODUCED_KINDS = {"scene", "npc", "item", "exit"}
_IMPLICIT_FENCE_KEYS = {"script": "code", "rule": "script"}


def _match_tag(
    line: str, *, allow_md_heading: bool = True
) -> tuple[str, str, str, str, int, int] | None:
    match = _TAG_RE.match(line)
    if match:
        word = normalize_key(match.group(3))
        if word not in _KIND_ALIASES:
            return None
        kind, preset_type = _KIND_ALIASES[word]
        indent = len(match.group(1).expandtabs(4))
        heading_level = len(match.group(2)) if match.group(2) else 0
        return (
            kind,
            preset_type,
            (match.group(4) or "").strip(),
            match.group(5).strip(),
            indent,
            heading_level,
        )
    if not allow_md_heading:
        return None
    return match_markdown_heading_tag(line, _KIND_ALIASES, _SINGLETON_KINDS)
