"""Scoped selectors preserve strict canonical evidence and replay boundaries."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.engine import turn_controls
from backend.engine.chpm import (
    appraisal_context,
    cognitive_proposal,
    motivation,
    passages,
    proposal_attempt,
    quote_references,
)
from backend.engine.chpm.errors import StaleControlError
from backend.engine.chpm.host_state import record
from backend.engine.chpm.schema import Decision, Settings, Usage
from tests.chpm_reference_fixture import proposal as reference_proposal
from tests.test_chpm_appraisal import heard
from tests.test_chpm_host_state import mind, source
from tests.test_chpm_kernel import observation, wire_proposal


def prepare(host=None, value=None, previous=None):
    host = host or SimpleNamespace(game_id="session")
    value = value or heard(message="input", text="The bridge is ready. The inspection is complete.")
    prepared = cognitive_proposal.prepare(
        host,
        Settings(mode="live", actor_ids=["npc"]),
        "npc",
        observation(),
        {},
        [],
        value,
        previous,
        pinned={},
        pinned_beliefs={},
        focus=(),
        hits=[],
        audit=[],
        notebook=None,
    )
    return host, value, prepared


def response(prepared):
    return reference_proposal(wire_proposal(), prepared.payload)


@pytest.mark.parametrize("length", [299, 300, 301, 599, 600, 601, 1000, 2000])
def test_fragments_are_bounded_exact_and_preserve_one_canonical_source(length):
    value = record(mind(), source(text="a" * length), minute=1)
    window = appraisal_context.build(value)
    table = quote_references.build(window, motivation.build(value, [], window), {})
    refs = list(table.quotes.values())
    assert all(0 < len(item.quote) <= 300 for item in refs)
    assert all(item.quote in window.sources[item.source_id][2] for item in refs)
    assert len({window.sources[item.source_id][0] for item in refs}) == 1
    projected = table.project({"appraisal_context": window.payload})
    row = projected["appraisal_context"]["visible_evidence"][0]
    assert "text" not in row
    assert "".join(row["fragments"].values()) == window.sources["e1"][2]
    assert window.payload["visible_evidence"][0]["text"] == window.sources["e1"][2]


def test_current_wire_materializes_belief_experience_and_choice_with_existing_quotes():
    _, original, prepared = prepare()
    raw = response(prepared)
    selector = {"fragment_id": next(iter(prepared.references.quotes))}
    raw["new_beliefs"] = [
        {
            "about_id": "@player",
            "domain": "reliability",
            "statement": "The report may be reliable",
            "stance": "support",
            "citations": [selector],
            "alternatives": [],
            "unknowns": [],
        }
    ]
    raw["experiences"] = [
        {
            "channel": "need_satisfaction",
            "dimension": "competence",
            "about_id": None,
            "level": "moderate",
            "citations": [selector],
            "personal_motive_ids": ["character"],
            "explanation": "The inspection may support bridge safety",
            "alternatives": [],
            "unknowns": [],
        }
    ]
    before = original.model_dump_json()
    decision, changed = prepared.accept(prepared.schema.model_validate(raw))
    assert len(changed.snapshot.beliefs) == len(changed.snapshot.experiences) == 1
    assert original.model_dump_json() == before
    saved = Decision.model_validate_json(decision.model_dump_json())
    assert saved == decision
    assert "fragment_id" not in saved.model_dump_json()
    assert "reference_scope" not in changed.model_dump_json()
    raw["choice"]["change_basis"] = [selector]
    canonical = prepared.schema.model_validate(raw).materialize(
        motivation.build(
            original, [], appraisal_context.build(original, current_message_id="input")
        ),
        prepared.references,
        [],
    )
    assert (
        canonical.choice.change_basis[0].quote
        == prepared.references.quote(selector["fragment_id"])["quote"]
    )


@pytest.mark.parametrize("field", ["new_beliefs", "belief_revisions", "experiences", "choice"])
def test_modern_response_schema_never_accepts_legacy_quote_objects(field):
    _, _, prepared = prepare()
    raw = response(prepared)
    citation = {"source_id": "e1", "quote": "The bridge is ready."}
    if field == "choice":
        raw["choice"]["change_basis"] = [citation]
    elif field == "belief_revisions":
        raw[field] = [
            {
                "belief_id": "b1",
                "stance": "support",
                "citations": [citation],
                "alternatives": [],
                "unknowns": [],
            }
        ]
    elif field == "new_beliefs":
        raw[field] = [
            {
                "about_id": "@player",
                "domain": "reliability",
                "statement": "A report",
                "stance": "support",
                "citations": [citation],
                "alternatives": [],
                "unknowns": [],
            }
        ]
    else:
        raw[field] = [
            {
                "channel": "affect",
                "dimension": "interest",
                "about_id": None,
                "level": "low",
                "citations": [citation],
                "personal_motive_ids": ["character"],
                "explanation": "A report",
                "alternatives": [],
                "unknowns": [],
            }
        ]
    with pytest.raises(ValidationError):
        prepared.schema.model_validate(raw)


def test_attempt_binding_changes_wire_scope_without_invalidating_semantic_replay_cache():
    host, value, first = prepare()
    decision, _ = first.accept(first.schema.model_validate(response(first)))
    turn_controls.begin(host)
    _, _, second = prepare(host, value, decision)
    assert first.references.scope != second.references.scope
    assert second.cached == (decision, value)
    with pytest.raises(StaleControlError):
        first.accept(first.schema.model_validate(response(first)))


def test_unknown_and_foreign_window_references_cannot_be_materialized():
    _, value, first = prepare()
    _, _, second = prepare(value=heard(value, "later", "A different report."))
    raw = response(first)
    raw["reference_scope"] = second.references.scope
    with pytest.raises(ValueError, match="unavailable|another prepared"):
        first.accept(first.schema.model_validate(raw))
    raw = response(first)
    raw["choice"]["change_basis"] = [{"fragment_id": "not-offered"}]
    with pytest.raises(ValueError, match="unavailable"):
        first.accept(first.schema.model_validate(raw))


async def test_expired_attempt_fails_without_spending_the_proposal_repair_allowance():
    host, _, prepared = prepare()
    original = prepared.schema.model_validate(response(prepared))
    turn_controls.begin(host)
    usage = Usage()

    async def initial():
        return original

    with pytest.raises(StaleControlError):
        await proposal_attempt.request(
            host,
            Settings(mode="live", actor_ids=["npc"]),
            usage,
            prepared.instruction,
            prepared.payload,
            prepared.schema,
            prepared.identifiers,
            prepared.accept,
            initial=initial,
        )
    assert usage.calls == usage.proposal_repairs == 0


def test_structured_review_rejections_resolve_codes_and_reject_stale_or_foreign_refs():
    body = {
        "review_scope": "scope",
        "matches": False,
        "rejections": [{"reason_code": "agenda", "actor_id": "npc", "passage_id": "p0"}],
    }
    review = passages.SharedReview.model_validate(body)
    passages.validate_shared(review, "scope", {"p0": "A spoken undertaking."}, {"npc"})
    assert review.issues == ["The spoken agenda differs from the selected change."]
    for key, replacement in (("actor_id", "foreign"), ("passage_id", "foreign")):
        bad = deepcopy(body)
        bad["rejections"][0][key] = replacement
        with pytest.raises(ValueError, match="unavailable"):
            passages.validate_shared(
                passages.SharedReview.model_validate(bad), "scope", {"p0": "Words"}, {"npc"}
            )
    with pytest.raises(ValueError, match="another prepared"):
        passages.validate_shared(review, "new-scope", {"p0": "Words"}, {"npc"})


@pytest.mark.parametrize("field", ["scope", "fragment", "motive", "preference", "subject"])
def test_modern_ids_are_rejected_before_legacy_readers_can_trim_them(field):
    _, _, prepared = prepare()
    raw = response(prepared)
    selector = next(iter(prepared.references.quotes))
    raw["new_beliefs"] = [
        {
            "about_id": "@player",
            "domain": "reliability",
            "statement": "A report may be reliable",
            "stance": "support",
            "citations": [{"fragment_id": selector}],
            "alternatives": [],
            "unknowns": [],
        }
    ]
    if field == "scope":
        raw["reference_scope"] = " " + raw["reference_scope"] + " "
    elif field == "fragment":
        raw["new_beliefs"][0]["citations"][0]["fragment_id"] = " " + selector + " "
    elif field == "motive":
        raw["candidates"]["CONTINUE"]["motives"][0]["motive_id"] = " goal1 "
    elif field == "preference":
        raw["choice"]["motive_ids"] = [" goal1 "]
    else:
        raw["new_beliefs"][0]["about_id"] = " @player "
    with pytest.raises(ValueError, match="unavailable"):
        prepared.accept(prepared.schema.model_validate(raw))


@pytest.mark.parametrize(
    "malformed", ["source-extra", "episode-extra", "episode-empty", "episode-missing"]
)
def test_fixture_migration_preserves_rejection_of_invalid_canonical_citations(malformed):
    from tests.test_chpm_development import history, proposal

    if malformed == "source-extra":
        _, _, prepared = prepare()
        raw = wire_proposal()
        citation = next(iter(prepared.references.quotes.values())).model_dump()
        raw["new_beliefs"] = [
            {
                "about_id": "@player",
                "domain": "reliability",
                "statement": "A report may be reliable",
                "stance": "support",
                "citations": [citation],
                "alternatives": [],
                "unknowns": [],
            }
        ]
    else:
        value = history()
        _, _, prepared = prepare(value=value)
        raw = wire_proposal()
        raw["developments"] = [proposal(value).model_dump(mode="json")]
        citation = raw["developments"][0]["citations"][0]
    valid = reference_proposal(raw, prepared.payload)
    prepared.accept(prepared.schema.model_validate(valid))
    if malformed.endswith("extra"):
        citation["root_ids"] = ["fabricated"]
    elif malformed.endswith("empty"):
        citation["quote"] = ""
    else:
        citation.pop("quote")
    invalid = reference_proposal(raw, prepared.payload)
    with pytest.raises(ValueError):
        prepared.accept(prepared.schema.model_validate(invalid))
