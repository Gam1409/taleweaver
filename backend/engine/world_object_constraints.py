"""Apply requested container and readable-object generation limits."""


def constrain_generated_objects(
    manifest_dict,
    max_containers,
    max_text_logs,
    scripts_generation_enabled,
    container_generation_enabled,
    text_log_generation_enabled,
):
    from backend.engine.world_generator import (
        _ensure_containers_have_minimum_inventory,
        _normalize_unlock_requirements,
    )

    # Post-processing: clamp container and text-log counts
    clamped_max_containers = (
        max(0, min(30, int(max_containers))) if max_containers is not None else 9999
    )
    clamped_max_text_logs = (
        max(0, min(30, int(max_text_logs))) if max_text_logs is not None else 9999
    )
    if not scripts_generation_enabled:
        manifest_dict["scripts"] = []

    objects = manifest_dict.get("objects") or []
    container_indices = [
        idx
        for idx, obj in enumerate(objects)
        if isinstance(obj, dict) and str(obj.get("item_type", "")).upper() == "CONTAINER"
    ]
    if not container_generation_enabled:
        for idx in container_indices:
            obj = objects[idx]
            obj["item_type"] = "PICKABLE"
            obj["inventory"] = []
            obj["code_to_unlock"] = ""
            obj["item_to_unlock"] = ""
            obj["rule_to_unlock"] = ""
    elif len(container_indices) > clamped_max_containers:
        for idx in container_indices[clamped_max_containers:]:
            obj = objects[idx]
            obj["item_type"] = "PICKABLE"
            obj["inventory"] = []
            obj["code_to_unlock"] = ""
            obj["item_to_unlock"] = ""
            obj["rule_to_unlock"] = ""

    for idx in container_indices[:clamped_max_containers]:
        obj = objects[idx]
        code, item, rule = _normalize_unlock_requirements(
            obj.get("code_to_unlock"), obj.get("item_to_unlock"), obj.get("rule_to_unlock")
        )
        obj["code_to_unlock"] = code
        obj["item_to_unlock"] = item
        obj["rule_to_unlock"] = rule

    _ensure_containers_have_minimum_inventory(objects)

    _constrain_readable_objects(objects, text_log_generation_enabled, clamped_max_text_logs)


def _constrain_readable_objects(objects, text_log_generation_enabled, clamped_max_text_logs):
    from backend.engine.world_generator import _normalize_text_log_content

    readable_indices = [
        idx
        for idx, obj in enumerate(objects)
        if isinstance(obj, dict) and str(obj.get("item_type", "")).upper() == "READABLE"
    ]
    if not text_log_generation_enabled:
        for idx in readable_indices:
            obj = objects[idx]
            obj["item_type"] = "PICKABLE"
            obj["text_log_content"] = ""
            obj["text_log_format"] = ""
    else:
        if len(readable_indices) > clamped_max_text_logs:
            for idx in readable_indices[clamped_max_text_logs:]:
                obj = objects[idx]
                obj["item_type"] = "PICKABLE"
                obj["text_log_content"] = ""
                obj["text_log_format"] = ""
        for idx in readable_indices[:clamped_max_text_logs]:
            obj = objects[idx]
            _obj_meta = obj.get("metadata_json") or {}
            obj["text_log_content"] = _normalize_text_log_content(
                obj.get("text_log_content") or _obj_meta.get("text_log_content"),
                obj.get("description"),
                obj.get("name"),
            )
            text_log_format = (
                str(obj.get("text_log_format") or _obj_meta.get("text_log_format") or "DOCUMENT")
                .strip()
                .upper()
            )
            if text_log_format not in {"DOCUMENT", "SCROLL", "BOOK", "SIGN"}:
                text_log_format = "DOCUMENT"
            obj["text_log_format"] = text_log_format
