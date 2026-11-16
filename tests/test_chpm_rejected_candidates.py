"""A missing explanation or unavailable recheck cannot erase a negative verdict."""

from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import continuation_writer, inference, passages, rendering
from backend.engine.chpm.errors import ChpmError, InferenceUnavailableError
from backend.engine.chpm.schema import Verdict
from tests.test_chpm_fallback import continuing


async def test_negative_verdict_without_feedback_still_uses_rejection_path(monkeypatch):
    host, turn = continuing()
    request = AsyncMock(return_value=passages.Review(matches=False, issues=[]))
    monkeypatch.setattr(inference, "request", request)
    monkeypatch.setattr(rendering, "_repair", AsyncMock(return_value="Still wrong"))
    fresh = AsyncMock(return_value="A fresh ordinary answer.")
    monkeypatch.setattr(continuation_writer, "generate", fresh)
    result = await rendering.validate(
        host, "Rejected original", completed=True, resolution="", system_prompt="Policy"
    )
    assert result == "A fresh ordinary answer."
    assert turn.simplified and turn.usage.fallback_reason == "review_rejected"
    fresh.assert_awaited_once()


@pytest.mark.parametrize("repair", ["Rejected original", "  Rejected original\n"])
async def test_echoed_repair_with_unavailable_reviewer_never_releases_rejected_text(
    monkeypatch, repair
):
    host, turn = continuing()
    monkeypatch.setattr(
        rendering,
        "_review",
        AsyncMock(
            side_effect=[
                Verdict(matches=False, issues=["Wrong action"]),
                InferenceUnavailableError("uncertain"),
            ]
        ),
    )
    monkeypatch.setattr(rendering, "_repair", AsyncMock(return_value=repair))
    fresh = AsyncMock(return_value="A fresh ordinary answer.")
    monkeypatch.setattr(continuation_writer, "generate", fresh)
    result = await rendering.validate(
        host, "Rejected original", completed=True, resolution="", system_prompt="Policy"
    )
    assert result == "A fresh ordinary answer."
    assert turn.simplified and turn.simplified_text == result
    fresh.assert_awaited_once()


async def test_different_repair_can_still_continue_unreviewed_without_an_extra_request(monkeypatch):
    host, turn = continuing()
    monkeypatch.setattr(
        rendering,
        "_review",
        AsyncMock(
            side_effect=[
                Verdict(matches=False, issues=["Wrong action"]),
                InferenceUnavailableError("uncertain"),
            ]
        ),
    )
    monkeypatch.setattr(
        rendering, "_repair", AsyncMock(return_value="A different repaired answer.")
    )
    fresh = AsyncMock(side_effect=AssertionError("Do not add a model call on transport failure"))
    monkeypatch.setattr(continuation_writer, "generate", fresh)
    result = await rendering.validate(
        host, "Rejected original", completed=True, resolution="", system_prompt="Policy"
    )
    assert result == "A different repaired answer."
    assert turn.usage.fallback_reason == "review_unavailable"
    fresh.assert_not_awaited()


@pytest.mark.parametrize("candidate", ["Rejected original", "Rejected repair"])
async def test_ordinary_writer_cannot_echo_either_rejected_candidate_or_publish_on_retry(
    monkeypatch, candidate
):
    host, turn = continuing()
    monkeypatch.setattr(
        rendering,
        "_review",
        AsyncMock(return_value=Verdict(matches=False, issues=["Wrong action"])),
    )
    monkeypatch.setattr(rendering, "_repair", AsyncMock(return_value="Rejected repair"))
    fresh = AsyncMock(return_value=candidate)
    monkeypatch.setattr(continuation_writer, "generate", fresh)
    with pytest.raises(ChpmError):
        await rendering.validate(
            host, "Rejected original", completed=True, resolution="", system_prompt="Policy"
        )
    assert turn.simplified_text is None
    with pytest.raises(ChpmError):
        await rendering.validate(
            host, "Rejected original", completed=True, resolution="", system_prompt="Policy"
        )
    fresh.assert_awaited_once()
