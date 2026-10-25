"""Author-owned NPC card visibility, independent of generated world content."""

from typing import Any

from pydantic import BaseModel, ConfigDict, StrictBool

MANIFEST_KEY = "npc_card_settings"
SETTINGS_KEY = "__npc_card_settings__"
SNAPSHOT_KEY = "__manifest_snapshot__"


class NpcCardSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    show_state: StrictBool = False


def _enabled(raw: Any) -> bool:
    """Malformed or legacy data cannot accidentally disclose character state."""
    return isinstance(raw, dict) and raw.get("show_state") is True


def manifest_card_settings(manifest: Any) -> dict[str, bool]:
    raw = manifest.get(MANIFEST_KEY) if isinstance(manifest, dict) else None
    return {"show_state": _enabled(raw)}


def preserve_card_settings(manifest: dict, adventure: Any) -> dict:
    """Generated content must never override an author's disclosure preference."""
    return {
        **manifest,
        MANIFEST_KEY: manifest_card_settings(getattr(adventure, "original_manifest", None)),
    }


def creation_manifest(manifest: Any, show_state: bool) -> dict:
    """Persist the explicit creation control before any LLM request or resume."""
    return {
        **(manifest if isinstance(manifest, dict) else {}),
        MANIFEST_KEY: {"show_state": show_state is True},
    }


def card_insights_enabled(state: Any) -> bool:
    """Prefer a session override, then its frozen source; never consult a live template."""
    states = getattr(state, "entity_states", None)
    if not isinstance(states, dict):
        return False
    if SETTINGS_KEY in states:
        return _enabled(states[SETTINGS_KEY])
    snapshot = states.get(SNAPSHOT_KEY)
    manifest = snapshot.get("original_manifest") if isinstance(snapshot, dict) else None
    return manifest_card_settings(manifest)["show_state"]
