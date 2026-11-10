"""Local identifiers must not disguise a pipeline bug as a provider failure."""

from types import SimpleNamespace

import pytest

from backend.engine.gameplay.manager import _friendly_llm_error_message


@pytest.mark.parametrize("digits", ["429", "502", "503", "504"])
def test_embedded_source_digits_are_not_a_provider_status(digits):
    error = ValueError(f"Unknown source 01a1c{digits}-4da7-7d2a-824d-a1034a72fb4a")
    assert _friendly_llm_error_message(error) is None


@pytest.mark.parametrize("status,phrase", [(429, "rate limit"), (503, "temporarily unavailable")])
@pytest.mark.parametrize("source", ["status_code", "response"])
def test_typed_provider_status_keeps_its_actionable_message(status, phrase, source):
    error = RuntimeError("Provider request failed")
    if source == "response":
        error.response = SimpleNamespace(status_code=status)
    else:
        error.status_code = status
    assert phrase in (_friendly_llm_error_message(error) or "")


@pytest.mark.parametrize(
    "text,phrase",
    [
        ("429 Too Many Requests", "rate limit"),
        ("HTTP 429", "rate limit"),
        ("status_code: 503", "temporarily unavailable"),
        ("503 Service Unavailable", "temporarily unavailable"),
    ],
)
def test_explicit_legacy_provider_status_is_still_recognized(text, phrase):
    assert phrase in (_friendly_llm_error_message(RuntimeError(text)) or "")


@pytest.mark.parametrize("digits", ["429", "503"])
async def test_local_turn_failure_is_logged_without_leaking_its_identifier(
    monkeypatch, caplog, digits
):
    import json
    import logging

    from backend.engine.gameplay.manager import GameTurnManager
    from tests.conftest import TestSessionLocal
    from tests.test_vn_turn_integration import TurnRoles, install_roles, seed_vn

    source_id = f"01a1c{digits}-4da7-7d2a-824d-a1034a72fb4a"

    class BrokenSourceRoles(TurnRoles):
        async def structured(self, *_args, **_kwargs):
            raise ValueError(f"Unknown source {source_id}")

    install_roles(monkeypatch, BrokenSourceRoles())
    async with TestSessionLocal() as db:
        user, _avatar, _state, _prior = await seed_vn(db)
        with caplog.at_level(logging.ERROR):
            events = [
                event
                async for event in GameTurnManager(db, "session-1", user).process_turn("I wait.")
            ]
    errors = [
        json.loads(event.split("data: ", 1)[1])
        for event in events
        if event.startswith("event: error")
    ]
    assert len(errors) == 1
    detail = errors[0]["detail"].lower()
    assert "quota" not in detail and "rate limit" not in detail
    assert "temporarily unavailable" not in detail
    assert source_id not in "".join(events)
    assert any(
        record.exc_info and isinstance(record.exc_info[1], ValueError) for record in caplog.records
    )
