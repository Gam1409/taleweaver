"""Shared limits for the number of Small-model reads per prose source."""

from typing import Annotated, Any

from pydantic import Field

MAX_PROSE_PASSES = 3
ProseExtractionPasses = Annotated[int, Field(strict=True, ge=1, le=MAX_PROSE_PASSES)]


def configured_passes(llm_settings: dict[str, Any] | None) -> int:
    value = (llm_settings or {}).get("prose_extraction_passes")
    return value if type(value) is int and 1 <= value <= MAX_PROSE_PASSES else 1
