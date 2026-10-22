"""Language policy for player-facing prose; engine tokens remain canonical."""

LANGUAGES = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "ja": "Japanese",
    "zh": "Chinese",
    "ru": "Russian",
    "pt": "Portuguese",
}


def normalize_language(value: str | None) -> str | None:
    """Accept existing selector names and ISO language codes, including locales."""
    if not value or not value.strip():
        return None
    token = value.strip().lower()
    if token in LANGUAGES:
        return LANGUAGES[token]
    if token in {name.lower() for name in LANGUAGES.values()}:
        return next(name for name in LANGUAGES.values() if name.lower() == token)
    base, separator, region = token.replace("_", "-").partition("-")
    if separator and base in LANGUAGES and region.isalpha() and len(region) in {2, 4}:
        return LANGUAGES[base]
    raise ValueError("Unsupported content language.")


def default_language(*values: str | None) -> str:
    """Resolve old profile/world preferences without breaking legacy sessions."""
    for value in values:
        try:
            normalized = normalize_language(value)
        except ValueError:
            continue
        if normalized:
            return normalized
    return "English"


def prose_language_instruction(language: str, fields: str = "narration and dialogue") -> str:
    """Explicit field scope avoids translating JSON keys and mechanical values."""
    target = normalize_language(language) or "English"
    return (
        f"\n\nCONTENT LANGUAGE: {target}. Write all {fields} in {target}, including "
        "descriptive prose, even when the source world or previous messages use another language. "
        "This explicit choice overrides language inferred from the context. "
        "Preserve the required output format. Never translate JSON keys, IDs, references, "
        "enum values, status-effect tokens (e.g. Poisoned), slash commands, command target IDs, "
        "scripts, expressions, unlock codes, voice tags (e.g. [curious]) or speaker identifiers. "
        "Keep existing entity names consistent with the supplied world; do not rename entities."
    )
