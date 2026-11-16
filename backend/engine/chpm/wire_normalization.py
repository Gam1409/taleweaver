"""Narrow transport aliases; never synthesize choices, sources or story facts."""

from typing import Any

from pydantic import BaseModel

from backend.engine.chpm.schema import ChoicePreference


def normalize(
    schema: type[BaseModel], candidate: dict, identifiers: dict[str, list[str]] | None
) -> tuple[dict, tuple[str, ...]]:
    """Copy only an unambiguous known singular choice ID into its canonical list."""
    field = schema.model_fields.get("choice")
    choice = candidate.get("choice")
    if field is None or field.annotation is not ChoicePreference or not isinstance(choice, dict):
        return candidate, ()
    alias: Any = choice.get("motive_id")
    if (
        "motive_ids" in choice
        or not isinstance(alias, str)
        or not 1 <= len(alias) <= 100
        or alias not in (identifiers or {}).get("motive_ids", ())
    ):
        return candidate, ()
    corrected = {key: value for key, value in choice.items() if key != "motive_id"}
    corrected["motive_ids"] = [alias]
    return {**candidate, "choice": corrected}, ("choice.motive_id->choice.motive_ids",)
