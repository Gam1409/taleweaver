"""Read explicit card facts without inferring identity from prose or clothing."""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel


def _get(actor: Any, key: str) -> Any:
    return actor.get(key) if isinstance(actor, dict) else getattr(actor, key, None)


def identity_facts(actor: Any) -> dict[str, Any]:
    gender = _get(actor, "gender")
    age = _get(actor, "age_years")
    profile = _get(actor, "visual_profile")
    if age is None and isinstance(profile, dict):
        appearance = profile.get("appearance")
        age = appearance.get("age_years") if isinstance(appearance, dict) else None
    facts: dict[str, Any] = {}
    if isinstance(gender, str) and gender.strip():
        facts["gender"] = gender.strip()
    if type(age) is int and 0 <= age <= 100000:
        facts["age_years"] = age
    return facts


def identity_text(actor: Any) -> str:
    return "; ".join(f"{key}: {value}" for key, value in identity_facts(actor).items())


def describe_character(actor: Any, description: str | None = None) -> str:
    description = _get(actor, "description") if description is None else description
    return "; ".join(part for part in (description or "", identity_text(actor)) if part)


def identity_profile(actor: Any, profile: Any) -> Any:
    """Overlay explicit card age on an existing profile without enabling managed clothing."""
    if not isinstance(profile, dict):
        return profile
    if not isinstance(profile.get("appearance", {}), dict):
        return profile
    result = deepcopy(profile)
    age = identity_facts(actor).get("age_years")
    if age is not None:
        result["appearance"] = {**(result.get("appearance") or {}), "age_years": age}
    return result


def update_identity(actor: Any, payload: BaseModel) -> None:
    """Omitted fields are unchanged; explicit null clears a card fact and its legacy age."""
    for key in ("gender", "age_years"):
        if key in payload.model_fields_set:
            value = getattr(payload, key)
            setattr(actor, key, value.strip() or None if isinstance(value, str) else value)
    if "age_years" in payload.model_fields_set and isinstance(actor.visual_profile, dict):
        profile = deepcopy(actor.visual_profile)
        appearance = profile.get("appearance")
        profile["appearance"] = {
            **(appearance if isinstance(appearance, dict) else {}),
            "age_years": actor.age_years,
        }
        actor.visual_profile = profile
