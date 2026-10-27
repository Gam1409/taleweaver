"""Object-reference annotation and authored sequence parsing for world manifests."""

import re
from typing import Any


def _annotate_narrative_fields(record, fields, replace_ids_in_text):
    if not isinstance(record, dict):
        return
    for field in fields:
        if field in record:
            record[field] = replace_ids_in_text(record[field])


def _normalize_sequence_requirements(sequence):
    if not isinstance(sequence, dict):
        return
    for field in ("required_item_id", "required_scene_id", "required_defeated_npc_id"):
        value = str(sequence.get(field) or "").replace("##", "").strip()
        if value.upper() in ("NONE", "NULL", "UNDEFINED", "N/A", "FALSE"):
            value = ""
        sequence[field] = value.upper() if value else ""


def preprocess_manifest_object_ids(manifest_dict: dict) -> None:
    """Replace bare object-ID references in narrative text with ##OBJECTID tokens.

    Finds all object IDs in the manifest and annotates references to them
    in all narrative text fields so the GM can resolve them deterministically.
    """
    if not isinstance(manifest_dict, dict):
        return
    objects = manifest_dict.get("objects", [])
    if not isinstance(objects, list):
        return

    object_ids = [
        obj.get("id").strip()
        for obj in objects
        if isinstance(obj, dict) and isinstance(obj.get("id"), str) and obj.get("id").strip()
    ]
    if not object_ids:
        return

    object_ids.sort(key=len, reverse=True)

    def replace_ids_in_text(text: Any) -> Any:
        if not isinstance(text, str) or not text:
            return text
        for obj_id in object_ids:
            pattern = rf"(?<!##)\b{re.escape(obj_id)}\b"
            text = re.sub(pattern, f"##{obj_id}", text, flags=re.IGNORECASE)
        return text

    _annotate_narrative_fields(
        manifest_dict,
        ("teaser", "plot", "rules", "intro_text", "completed_condition", "gameover_condition"),
        replace_ids_in_text,
    )

    protagonist = manifest_dict.get("protagonist")
    _annotate_narrative_fields(
        protagonist, ("description", "goal", "character"), replace_ids_in_text
    )

    _annotate_world_entity_text(manifest_dict, objects, replace_ids_in_text)

    for quest in manifest_dict.get("quests") or []:
        _annotate_narrative_fields(
            quest, ("title", "description", "goal", "impact"), replace_ids_in_text
        )

    for award in manifest_dict.get("awards") or []:
        _annotate_narrative_fields(
            award, ("title", "description", "requirement"), replace_ids_in_text
        )

    for seq in manifest_dict.get("sequences") or []:
        _annotate_narrative_fields(
            seq, ("title", "description", "walkthrough", "end_condition"), replace_ids_in_text
        )
        _normalize_sequence_requirements(seq)


def _extract_sequences_from_prompt(prompt_str: str) -> tuple[str, list[dict[str, Any]]]:
    if not prompt_str:
        return prompt_str, []
    seq_regex = re.compile(r"\[Sequence[\s:]*\d*\]", re.IGNORECASE)
    if not seq_regex.search(prompt_str):
        return prompt_str, []
    blocks = seq_regex.split(prompt_str)
    cleaned_prompt = blocks[0].strip()
    sequences: list[dict[str, Any]] = []

    for i, block in enumerate(blocks[1:], start=1):
        if len(sequences) >= 15:
            break
        sequences.append(_parse_sequence_block(i, block))
    return cleaned_prompt, sequences


def _clean_id(raw_val: str) -> str:
    clean = raw_val.replace("##", "").strip().strip("\"'").strip()
    if clean.upper() in ("NONE", "NULL", "UNDEFINED", "N/A", "FALSE"):
        return ""
    return clean.upper()


def _parse_sequence_block(i, block):
    lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
    title = lines[0] if lines else f"Sequence {i}"
    raw_lines = lines[1:] if len(lines) > 1 else []
    desc_lines: list[str] = []
    req_item = ""
    req_scene = ""
    req_defeated_npc = ""
    custom_end_condition = ""

    for line in raw_lines:
        item_match = re.match(
            r"^(?:required[_\s]+item(?:[_\s]+id)?|key[_\s]+item|item(?:[_\s]+id)?)\s*:\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        scene_match = re.match(
            r"^(?:required[_\s]+scene(?:[_\s]+id)?|target[_\s]+scene|scene(?:[_\s]+id)?)\s*:\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        npc_match = re.match(
            r"^(?:required[_\s]+defeated[_\s]+npc(?:[_\s]+id)?|defeated[_\s]+npc(?:[_\s]+id)?|defeat[_\s]+npc(?:[_\s]+id)?|defeat|npc[_\s]+to[_\s]+defeat)\s*:\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        cond_match = re.match(
            r"^(?:end[_\s]+condition|completion[_\s]+condition|condition)\s*:\s*(.+)$",
            line,
            re.IGNORECASE,
        )

        if item_match:
            req_item = _clean_id(item_match.group(1))
        elif scene_match:
            req_scene = _clean_id(scene_match.group(1))
        elif npc_match:
            req_defeated_npc = _clean_id(npc_match.group(1))
        elif cond_match:
            custom_end_condition = cond_match.group(1).strip()
        else:
            desc_lines.append(line)

    desc = "\n".join(desc_lines) if desc_lines else "Follow the sequence blueprint."
    end_cond = custom_end_condition or "Complete the sequence objectives."
    return {
        "id": f"SEQ_{i}",
        "order": i,
        "title": title,
        "description": desc[:500],
        "walkthrough": desc,
        "end_condition": end_cond,
        "required_item_id": req_item,
        "required_scene_id": req_scene,
        "required_defeated_npc_id": req_defeated_npc,
        "exp_reward": 100,
    }


def _annotate_world_entity_text(manifest_dict, objects, replace_ids_in_text):
    for scene in manifest_dict.get("scenes") or []:
        _annotate_narrative_fields(scene, ("description",), replace_ids_in_text)

    for exit_val in manifest_dict.get("exits") or []:
        _annotate_narrative_fields(
            exit_val, ("label", "lock_description", "rule_to_unlock"), replace_ids_in_text
        )

    for npc in manifest_dict.get("npcs") or []:
        _annotate_narrative_fields(
            npc,
            ("description", "goal", "character", "spatial_position", "reveal_rule"),
            replace_ids_in_text,
        )

    for obj in objects:
        _annotate_narrative_fields(
            obj,
            (
                "description",
                "spatial_position",
                "reveal_rule",
                "text_log_content",
                "rule_to_unlock",
            ),
            replace_ids_in_text,
        )
