"""Shared profile selection and readiness checks for image entry points."""

from backend.core.comfyui_config import select_workflow
from backend.core.config import settings

LOCAL_IMAGE_PROVIDERS = ("ollama", "stable_diffusion", "comfyui")
PROFILE_SETTINGS = {
    "scene": ("scene_model_quality", "advanced"),
    "npc": ("profile_model_quality", "advanced"),
    "protagonist": ("protagonist_model_quality", "advanced"),
    "object": ("asset_model_quality", "simple"),
    "cover": ("cover_model_quality", "advanced"),
}


def advanced_for(t2i: dict, kind: str, override: bool | None = None) -> bool:
    if override is not None:
        return override
    key, default = PROFILE_SETTINGS[kind]
    return t2i.get(key, default) == "advanced"


def image_timeout(t2i: dict | None) -> float:
    data = t2i or {}
    uses_comfy = any(data.get(f"{p}_model_provider") == "comfyui" for p in ("simple", "advanced"))
    return (
        float(data.get("comfyui_timeout") or 600) + 135
        if uses_comfy
        else float(settings.VISUAL_TIMEOUT)
    )


def validate_image_profiles(user, kinds: list[str]) -> None:
    if not user:
        return
    t2i = user.t2i_settings or {}
    profiles = {"advanced" if advanced_for(t2i, kind) else "simple" for kind in kinds}
    for profile in profiles:
        _validate_profile(t2i, user.encrypted_api_keys or {}, profile)


def _validate_profile(t2i: dict, keys: dict, profile: str) -> None:
    provider = (t2i.get(f"{profile}_model_provider") or t2i.get("provider", "openai")).lower()
    if provider == "comfyui":
        select_workflow({**t2i, "comfyui_profile": profile})
        return
    if not t2i.get(f"{profile}_model"):
        raise ValueError(f"Configure the {profile} image model in Visual Preferences.")
    if (
        provider not in LOCAL_IMAGE_PROVIDERS
        and not settings.get_env_api_key(provider)
        and provider not in keys
    ):
        raise ValueError(f"API key missing for {profile} image provider '{provider}'.")
