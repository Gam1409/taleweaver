"""Blueprint fields derive from this fork's actual world schema, including identity and clothing."""

import re
import types
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, TypeAdapter, ValidationError

from backend.engine.blueprint.converters import (
    boolean,
    ident_list,
    integer,
    json_value,
    normalize_id,
    text,
)
from backend.engine.world_schemas import (
    AwardTemplateSchema,
    ProtagonistSchema,
    QuestSchema,
    SequenceSchema,
    SpecialActionSchema,
    WorldExitSchema,
    WorldManifesto,
    WorldNPCSchema,
    WorldObjectSchema,
    WorldSceneSchema,
    WorldScriptSchema,
)

FieldRole = Literal["text", "script", "expr", "ref", "refs"]


@dataclass(frozen=True)
class FieldSpec:
    target: str
    convert: Callable[[str], Any] = text
    role: FieldRole = "text"
    repeat: bool = False


SCHEMAS: dict[str, type[BaseModel]] = {
    "world": WorldManifesto,
    "protagonist": ProtagonistSchema,
    "scene": WorldSceneSchema,
    "exit": WorldExitSchema,
    "npc": WorldNPCSchema,
    "item": WorldObjectSchema,
    "sequence": SequenceSchema,
    "script": WorldScriptSchema,
    "sidequest": QuestSchema,
    "award": AwardTemplateSchema,
    "ability": SpecialActionSchema,
}
COLLECTION_FIELDS = {
    "protagonist",
    "scenes",
    "exits",
    "npcs",
    "objects",
    "sequences",
    "quests",
    "awards",
    "scripts",
}
REF_FIELDS = {
    "from_scene_id",
    "to_scene_id",
    "start_scene_id",
    "item_to_unlock",
    "required_item_id",
    "required_scene_id",
    "required_defeated_npc_id",
    "reveals_item_id",
    "source_asset_id",
}
REF_LIST_FIELDS = {"starting_inventory", "inventory", "allowed_scenes", "combination_ingredients"}


def normalize_key(raw: str) -> str:
    return re.sub(r"[\s-]+", "_", raw.strip().lower())


def _plain_type(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin is Annotated:
        return _plain_type(get_args(annotation)[0])
    if origin in (Union, types.UnionType):
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        return _plain_type(args[0]) if len(args) == 1 else annotation
    return annotation


def _converter(name: str, annotation: Any) -> Callable[[str], Any]:
    plain = _plain_type(annotation)
    if name in REF_FIELDS:
        return normalize_id
    if name in REF_LIST_FIELDS:
        return lambda raw: json_value(raw) if raw.lstrip().startswith("[") else ident_list(raw)
    if plain is bool:
        return boolean
    if plain is int:
        return integer
    if plain is str or get_origin(plain) is Literal:
        return text
    return json_value


def _validated(raw: str, *, convert: Callable[[str], Any], adapter: TypeAdapter) -> Any:
    try:
        return adapter.dump_python(adapter.validate_python(convert(raw)), mode="json")
    except ValidationError as exc:
        error = exc.errors(include_url=False)[0]
        path = ".".join(str(part) for part in error["loc"])
        raise ValueError(f"{path + ': ' if path else ''}{error['msg']}") from exc


def _specs(kind: str, model: type[BaseModel]) -> dict[str, FieldSpec]:
    result = {}
    for name, info in model.model_fields.items():
        if kind == "world" and name in COLLECTION_FIELDS:
            continue
        role: FieldRole = "text"
        if name.endswith("_script") or (kind == "script" and name == "code"):
            role = "script"
        elif name.endswith("expression"):
            role = "expr"
        elif name in REF_FIELDS:
            role = "ref"
        elif name in REF_LIST_FIELDS:
            role = "refs"
        convert = partial(
            _validated,
            convert=_converter(name, info.annotation),
            adapter=TypeAdapter(info.rebuild_annotation()),
        )
        result[name] = FieldSpec(name, convert, role)
    return result


KEY_TABLES = {kind: _specs(kind, model) for kind, model in SCHEMAS.items()}
ALIASES = {
    "world": {
        "intro": "intro_text",
        "win": "completed_condition",
        "lose": "gameover_condition",
        "win_guard": "completed_guard_expression",
        "lose_guard": "gameover_guard_expression",
    },
    "protagonist": {"inventory": "starting_inventory", "age": "age_years"},
    "scene": {
        "decor": "decorative_objects",
        "on_enter": "on_enter_scene_script",
        "on_leave": "on_leave_scene_script",
    },
    "npc": {
        "in": "start_scene_id",
        "age": "age_years",
        "position": "spatial_position",
        "type": "npc_type",
    },
    "item": {
        "in": "start_scene_id",
        "type": "item_type",
        "portable": "is_portable",
        "text": "text_log_content",
    },
    "exit": {
        "via": "label",
        "locked": "is_locked",
        "key_item": "item_to_unlock",
        "code": "code_to_unlock",
        "guard": "unlock_expression",
    },
    "sequence": {
        "goal_item": "required_item_id",
        "goal_scene": "required_scene_id",
        "guard": "guard_expression",
        "on_start": "on_start_sequence_script",
        "on_end": "on_end_sequence_script",
    },
    "script": {"target": "target_id"},
}
for _kind, _aliases in ALIASES.items():
    for _alias, _target in _aliases.items():
        if _target in KEY_TABLES[_kind]:
            KEY_TABLES[_kind][_alias] = KEY_TABLES[_kind][_target]

DEPRECATED_KEYS: dict[tuple[str, str], str] = {}
