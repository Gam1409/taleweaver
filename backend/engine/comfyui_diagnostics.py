"""Describe the actual selected workflow without exposing URLs or arbitrary inputs."""

from pathlib import PurePosixPath

from backend.core.comfyui_config import ComfyWorkflow, select_profile

MODEL_INPUTS = {
    "unet_name": "models/diffusion_models (or legacy models/unet)",
    "ckpt_name": "models/checkpoints",
    "vae_name": "models/vae",
    "clip_name": "models/text_encoders (or legacy models/clip)",
    "clip_name1": "models/text_encoders (or legacy models/clip)",
    "clip_name2": "models/text_encoders (or legacy models/clip)",
    "clip_name3": "models/text_encoders (or legacy models/clip)",
}


def _label(value: object, limit: int = 120) -> str:
    return " ".join(str(value or "").split())[:limit]


def model_files(workflow: ComfyWorkflow) -> list[dict[str, str]]:
    files = []
    for node_id, node in workflow.graph.items():
        for name, folder in MODEL_INPUTS.items():
            value = node["inputs"].get(name)
            if not isinstance(value, str) or not value or "://" in value:
                continue
            filename = PurePosixPath(value.replace("\\", "/")).name
            files.append(
                {
                    "node": _label(node_id),
                    "loader": _label(node["class_type"]),
                    "input": name,
                    "file": _label(filename, 200),
                    "folder": folder,
                }
            )
            if len(files) >= 16:
                return files
    return files


def workflow_context(options: dict, workflow: ComfyWorkflow) -> str:
    profile = select_profile(options)
    preset = _label(getattr(profile, "name", "")) or "legacy quality profile"
    task = _label(options.get("image_purpose") or options.get("comfyui_profile") or "simple")
    summary = f'Task: {task}. Preset: "{preset}". Workflow: "{_label(workflow.name)}".'
    files = "; ".join(
        f"{file['loader']}.{file['input']}={file['file']} in ComfyUI/{file['folder']}"
        for file in model_files(workflow)
    )
    if files:
        summary += f" Model files: {files}."
    return summary + (
        " Check this task's assignment and the adventure's image preset source. "
        "A successful test preset does not change task or saved adventure assignments."
    )
