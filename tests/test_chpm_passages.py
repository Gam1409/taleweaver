"""Review passage references resolve to literal text, never reconstructed speech."""

from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import inference, passages, rendering
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.passages import Reference, Review
from tests.test_chpm_runtime import prepared


@pytest.mark.parametrize(
    "text",
    [
        'She nodded.\n"Start with the joints."\nHe looked away.\n"Then the supports."',
        "Она улыбнулась. «Начнём со стыков».\n— Потом опоры!",
        "Line without punctuation\nAnother line without punctuation",
        "Я" * 2001,
    ],
)
def test_every_indexed_passage_is_a_bounded_exact_substring(text):
    indexed = passages.index(text)
    assert indexed
    assert all(0 < len(quote) <= 600 and quote in text for quote in indexed.values())


async def test_review_resolves_passage_instead_of_retyping_quoted_text(monkeypatch):
    host = prepared()
    text = "She nodded.\nLet us discuss the repair.\nHe looked away."
    indexed = passages.index(text)
    identifier = next(
        key for key, value in indexed.items() if value == "Let us discuss the repair."
    )
    verdict = Review(matches=True, evidence=[Reference(actor_id="npc", passage_id=identifier)])
    monkeypatch.setattr(inference, "request", AsyncMock(return_value=verdict))
    assert (
        await rendering.validate(host, text, completed=True, resolution="", system_prompt="Policy")
        == text
    )
    assert host._chpm_turn.verdict.evidence[0].quote == "Let us discuss the repair."
    assert (
        verdict.evidence[0].passage_id == identifier
    )  # No mutation of the accepted model proposal.


def test_unknown_references_are_rejected():
    verdict = Review(matches=True, evidence=[Reference(actor_id="npc", passage_id="missing")])
    with pytest.raises(ChpmError):
        passages.resolve(verdict, {"p0": "Actual source words"})
