"""Keyword contract shared by generation bounds and the world generator."""

from typing import TypedDict


class GenerationBounds(TypedDict):
    min_sequences: int | None
    max_sequences: int | None
    min_scenes: int | None
    max_scenes: int | None
    min_items: int | None
    max_items: int | None
    min_containers: int | None
    max_containers: int | None
    min_text_logs: int | None
    max_text_logs: int | None
    min_quests: int | None
    max_quests: int | None
    min_awards: int | None
    max_awards: int | None
