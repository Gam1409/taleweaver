"""Remove configuration and session-only payloads, never authored NPC motivations."""

import re
from typing import Any

from backend.engine.adventure_compat.common import CompatibilityError, ConversionReport

_PRIVATE = frozenset(
    [
        "api_key",
        "apikey",
        "authorization",
        "password",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "secret_key",
        "encryption_key",
        "credentials",
        "endpoint",
        "endpoint_url",
        "base_url",
        "baseurl",
        "api_url",
        "provider_url",
        "url",
        "ollama_url",
        "custom_openai_url",
        "comfyui_url",
        "embeddings_url",
        "llm_config",
        "provider_config",
        "model_settings",
        "settings",
        "user_settings",
        "session_settings",
        "config",
        "providers",
        "provider",
        "credentials_vault",
        "llm_settings",
        "embeddings_settings",
        "chat_messages",
        "messages",
        "journal",
        "npc_journal",
        "npc_journals",
        "learned_history",
        "memory_context",
        "world_memories",
        "world_rumors",
        "compressed_history",
        "memory_summaries",
        "memory_index",
        "private_social_state",
        "social_state",
        "vn_social_state",
        "entity_states",
        "exit_states",
        "generation_checkpoint",
        "generation_request",
        "last_error",
        "lease_token",
        "session_id",
        "user_id",
        "owner_id",
        "hashed_password",
        "private_notes",
    ]
)


def _private_key(key: str) -> bool:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower().replace("-", "_")
    return normalized in _PRIVATE or normalized.endswith(
        (
            "_api_key",
            "_apikey",
            "_token",
            "_secret",
            "_password",
            "_endpoint",
            "_endpoint_url",
            "_base_url",
            "_api_url",
        )
    )


def public_content(
    value: Any, report: ConversionReport, script_names: frozenset[str] = frozenset()
) -> Any:
    if isinstance(value, list):
        return [public_content(item, report, script_names) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned = {}
    for key, item in value.items():
        if _private_key(key):
            if key in script_names:
                raise CompatibilityError(
                    "A script references data excluded from publication; review the adventure manually."
                )
            report.warn(
                "Private session data or configuration-like fields were excluded; review any custom authored metadata before publishing.",
                acknowledge=True,
            )
            continue
        cleaned[key] = public_content(item, report, script_names)
    return cleaned
