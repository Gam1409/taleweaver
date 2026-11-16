"""A bounded prompt window is not an authorization list for stored developmental facts."""

import pytest

from backend.engine.chpm import development_context
from tests.test_chpm_development import accept, history, proposal


def five_tendencies():
    mind = history(speaker="@player")
    for domain in ["reliability", "competence", "benevolence", "affection", "boundaries"]:
        mind, _ = accept(
            mind,
            proposal(
                mind,
                category="relationship",
                about_id="@player",
                relationship_domain=domain,
                statement=f"Developing {domain}",
            ),
            "create-" + domain,
        )
    visible = development_context.tendencies(mind)
    hidden = next(
        belief
        for belief in mind.snapshot.beliefs
        if belief.id not in {item["development_id"] for item in visible}
    )
    return mind, hidden


def test_oldest_of_five_tendencies_can_be_challenged_without_expanding_the_prompt():
    mind, old = five_tendencies()
    changed, _ = accept(
        mind,
        proposal(
            mind,
            category="relationship",
            about_id="@player",
            relationship_domain=old.domain.rsplit(".", 1)[1],
            statement=old.statement,
            existing_id=old.id,
            stance="challenge",
        ),
        "challenge-hidden",
    )
    assert len(development_context.tendencies(changed)) == 4
    assert next(b for b in changed.snapshot.beliefs if b.id == old.id).status == "challenged"
    assert changed.genesis.identity == mind.genesis.identity


@pytest.mark.parametrize(
    "change",
    [
        {"statement": "Rewrite the person"},
        {"relationship_domain": "affection"},
        {"existing_id": "unknown"},
    ],
)
def test_full_ledger_lookup_still_rejects_rewrites_and_unknown_ids(change):
    mind, old = five_tendencies()
    values = dict(
        category="relationship",
        about_id="@player",
        relationship_domain=old.domain.rsplit(".", 1)[1],
        statement=old.statement,
        existing_id=old.id,
        stance="challenge",
    )
    values.update(change)
    with pytest.raises(ValueError):
        accept(mind, proposal(mind, **values), "invalid-revision")
