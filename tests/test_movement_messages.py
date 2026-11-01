"""Player text uses the selected language without exposing mechanical details."""

from backend.api.routes.adventures.guardrails.movement_messages import movement_message
from backend.core.content_language import LANGUAGES


def test_russian_movement_outcomes():
    assert movement_message("Мики", False, "ru-RU") == "Мики остаётся здесь."
    assert (
        movement_message("Мики", True, "Russian")
        == "Мики не может перейти в эту локацию и остаётся на месте."
    )


def test_supported_languages_and_legacy_fallback():
    for language in LANGUAGES:
        for restricted in (False, True):
            assert "Miki" in movement_message("Miki", restricted, language)
    assert movement_message("Miki", False, None) == "Miki stays here."
