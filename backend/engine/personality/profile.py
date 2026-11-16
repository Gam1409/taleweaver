"""Canonical personality choices; tendencies never override events or agency."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

# One catalog drives the editor, JSON schema, validation and inference explanations.
CATALOG = {
    "temperament": (
        "Temperament",
        {
            "calm": ("Calm", "Usually composed; can still react strongly under pressure."),
            "energetic": ("Energetic", "Readily engages and takes initiative."),
            "hot_tempered": (
                "Hot-tempered",
                "Quick to anger, but capable of restraint and regret.",
            ),
            "melancholic": (
                "Melancholic",
                "Reflective and sensitive to loss; still capable of joy.",
            ),
        },
    ),
    "sociability": (
        "Sociability",
        {
            "reserved": ("Reserved", "Prefers limited social contact; opens up with trust."),
            "selective": ("Selective", "Engages warmly with chosen people."),
            "outgoing": ("Outgoing", "Readily starts conversations and seeks company."),
        },
    ),
    "speech": (
        "Communication style",
        {
            "direct": ("Direct", "States intentions plainly."),
            "diplomatic": ("Diplomatic", "Chooses words carefully to preserve cooperation."),
            "ironic": ("Ironic", "Sometimes uses dry humor; do not make every line a joke."),
            "gentle": ("Gentle", "Usually speaks with care for others' feelings."),
        },
    ),
    "trust": (
        "Trust in others",
        {
            "trusting": ("Trusting", "Initially gives others the benefit of the doubt."),
            "cautious": ("Cautious", "Builds trust gradually through evidence."),
            "suspicious": ("Suspicious", "Checks motives; shared experience can earn trust."),
        },
    ),
    "value": (
        "Core value",
        {
            "freedom": ("Freedom", "Values autonomy and voluntary choices."),
            "duty": ("Duty", "Takes responsibilities and commitments seriously."),
            "family": ("Family", "Prioritizes family and close personal bonds."),
            "justice": ("Justice", "Cares about fairness and accountability."),
            "knowledge": ("Knowledge", "Seeks understanding and reliable evidence."),
        },
    ),
    "conflict": (
        "Conflict approach",
        {
            "negotiate": ("Negotiate", "Looks for workable agreements."),
            "confront": ("Confront", "Directly challenges opposition."),
            "avoid": ("Avoid", "Prefers to de-escalate or withdraw when possible."),
            "yield": ("Yield", "Often compromises to protect harmony; still has boundaries."),
        },
    ),
    "risk": (
        "Risk tolerance",
        {
            "cautious": ("Cautious", "Prefers safer options and preparation."),
            "calculated": ("Calculated", "Weighs likely costs and benefits before acting."),
            "bold": ("Bold", "Accepts danger for meaningful goals; can still feel fear."),
            "impulsive": ("Impulsive", "Often acts before fully considering consequences."),
        },
    ),
}


def choice(key: str) -> Any:
    return Field(default="", json_schema_extra={"enum": ["", *CATALOG[key][1]]})


class PersonalityProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temperament: str = choice("temperament")
    sociability: str = choice("sociability")
    speech: str = choice("speech")
    trust: str = choice("trust")
    value: str = choice("value")
    conflict: str = choice("conflict")
    risk: str = choice("risk")

    @field_validator("*")
    @classmethod
    def validate_choice(cls, value: str, info: ValidationInfo) -> str:
        if value and (info.field_name is None or value not in CATALOG[info.field_name][1]):
            raise ValueError("Unknown personality choice")
        return value


def read_profile(entity: Any) -> PersonalityProfile:
    metadata = (
        entity.get("metadata_json", {})
        if isinstance(entity, dict)
        else getattr(entity, "metadata_json", {})
    )
    raw = metadata.get("personality_profile", {}) if isinstance(metadata, dict) else {}
    if not isinstance(raw, dict):
        return PersonalityProfile()
    # Old or third-party archives may contain unknown values. Preserve stored data,
    # but only use recognized choices as behavioral instructions.
    known = {
        key: raw[key]
        for key in CATALOG
        if isinstance(raw.get(key), str) and raw[key] in CATALOG[key][1]
    }
    return PersonalityProfile.model_validate(known)


def personality_context(entity: Any) -> str:
    profile = read_profile(entity).model_dump(exclude_defaults=True)
    if not profile:
        return ""
    traits = [f"{CATALOG[key][0]}: {CATALOG[key][1][value][1]}" for key, value in profile.items()]
    return (
        "Authored tendencies (not rigid rules; current events, relationships and explicit boundaries still matter). "
        "Closeness changes relationships, not automatically voice, values or independent goals. "
        "Show earned development without treating a temporary mood as a new identity: "
        + " ".join(traits)
    )


def catalog_payload() -> list[dict]:
    return [
        {
            "key": key,
            "label": label,
            "options": [
                {"value": value, "label": title, "help": help_text}
                for value, (title, help_text) in options.items()
            ],
        }
        for key, (label, options) in CATALOG.items()
    ]
