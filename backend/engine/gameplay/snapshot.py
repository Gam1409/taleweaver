"""Detached adventure data retained by sessions after a template is deleted."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass
class AdventureSnapshot:
    id: str
    title: str
    teaser: str | None
    version: str | None
    language: str | None
    image_url: str | None
    strict_rules: bool
    rule_enforcement_mode: str
    time_per_turn: int
    pacing_minutes: int
    clock_enabled: bool
    time_system: str
    time_config: dict[str, Any]
    selected_tone: dict[str, Any] | str | None
    selected_image_styles: list[dict[str, Any]]
    quests: list[dict[str, Any]]
    awards: list[dict[str, Any]]
    plot: str | None
    rules: str | None
    intro_text: str | None
    walkthrough: str | None
    completed_condition: str | None
    gameover_condition: str | None
    tts_director_notes: str | None
    original_prompt: str
    allow_dynamic_items: bool
    can_damage_npcs: bool
    npcs_can_damage_protagonist: bool
    is_adventure_generator: bool
    original_manifest: dict[str, Any]
    sequences: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        """Prefer captured chapter definitions, including an explicitly cleared list."""
        source = self.sequences
        if not isinstance(source, list):
            source = self.original_manifest.get("sequences")
        self.sequences = (
            [deepcopy(sequence) for sequence in source if isinstance(sequence, dict)]
            if isinstance(source, list)
            else []
        )
