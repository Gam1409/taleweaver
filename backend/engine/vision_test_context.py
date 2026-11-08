"""Use the visible test input and report which draft versus saved workflow ran."""

from typing import Any

from backend.core.comfyui_config import ComfySettings, prompt_rules, select_profile, select_workflow
from backend.core.comfyui_presets import normalize_comfy_presets
from backend.engine.comfyui_diagnostics import model_files

EXAMPLES = {
    "object": "A brass lantern, isolated on a simple background",
    "background": "An empty stone courtyard at dawn",
    "illustration": "A traveler hands a lantern to a guard in a courtyard",
    "cover": "A cinematic view of a castle above the clouds",
    "catalog": "A small woodland cottage in soft watercolor",
}


def test_input(payload: Any) -> tuple[str, str]:
    if payload.prepared_body is not None:
        return payload.prepared_body, "preview"
    if payload.test_prompt is not None:
        return payload.test_prompt, "description"
    return EXAMPLES.get(payload.image_purpose or "npc", "A Wizard portrait"), "builtin"


def _selection(options: dict) -> dict:
    profile = select_profile(options)
    workflow = select_workflow(options)
    assignments = options.get("comfyui_assignments", {})
    key = assignments.get(options.get("image_purpose")) or assignments.get(
        options.get("comfyui_profile", "simple")
    )
    return {
        "preset_id": key,
        "preset_name": getattr(profile, "name", "Legacy quality profile"),
        "workflow_name": workflow.name,
        "models": model_files(workflow),
    }


def configuration(options: dict, saved_settings: dict | None, prompt_source: str) -> dict:
    saved_options = {
        **normalize_comfy_presets(saved_settings or {}),
        "comfyui_profile": options.get("comfyui_profile", "simple"),
        "image_purpose": options.get("image_purpose"),
    }
    tested = _selection(options)
    try:
        saved = _selection(saved_options)
        same_server = ComfySettings.model_validate(options).comfyui_url.strip().rstrip(
            "/"
        ) == ComfySettings.model_validate(saved_options).comfyui_url.strip().rstrip("/")
        same_preset = _effective(options) == _effective(saved_options)
    except ValueError:
        saved, same_server, same_preset = None, False, False
    return {
        "scope": "draft",
        "prompt_source": prompt_source,
        "task": options.get("image_purpose") or options.get("comfyui_profile", "simple"),
        "tested": tested,
        "saved": saved,
        "matches_saved": same_server and same_preset,
        "same_server": same_server,
    }


def _effective(options: dict) -> tuple:
    rules = prompt_rules(options)
    return (
        select_workflow(options).model_dump(exclude={"name"}),
        rules.model_dump() if rules else None,
        bool(getattr(select_profile(options), "mature_themes", False)),
    )


def result_message(report: dict) -> str:
    tested = report["tested"]
    lines = [
        "Image generation successful!",
        f'Tested preset: "{tested["preset_name"]}" (ID: {tested["preset_id"] or "legacy"}).',
        f'Workflow: "{tested["workflow_name"]}".',
        *(f"{file['loader']}.{file['input']}: {file['file']}" for file in tested["models"]),
    ]
    if report["matches_saved"]:
        return "\n".join(
            [
                *lines,
                "This test matches the saved global configuration for this task.",
                "Adventure-specific saved selections can still use a different preset.",
            ]
        )
    lines.append(f"This draft differs from saved settings for {report['task']}.")
    if report["saved"]:
        lines.extend(
            f"Saved {file['loader']}.{file['input']}: {file['file']}"
            for file in report["saved"]["models"]
        )
    if not report["same_server"]:
        lines.append(
            "The tested server connection differs from the saved connection or is not configured."
        )
    lines.append(
        "Apply the preset, apply assignments, then Save Visuals Settings. Adventure-specific saved selections can still override global assignments."
    )
    return "\n".join(lines)
