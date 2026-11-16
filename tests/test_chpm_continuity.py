"""Matched source histories preserve identity; outcomes remain manual judgements."""

import json
from collections import defaultdict
from types import SimpleNamespace

import pytest

from backend.engine.chpm.evaluation import continuity_cases, matrix_cases, matrix_cli, matrix_runner
from backend.engine.chpm.identity_adapter import from_actor
from tests.test_chpm_matrix import Models


def test_matched_variants_keep_every_authored_identity_field_and_goal():
    groups = defaultdict(list)
    cases = matrix_cases.choose("continuity", [])
    assert len(cases) == len({c.id for c in cases}) == 15
    for case in cases:
        groups[case.persona].append(case)
    for variants in groups.values():
        identities = [from_actor(matrix_cases.actors(c)[0]) for c in variants]
        assert all(identity == identities[0] for identity in identities)
        neutral = [c for c in variants if c.context_variant != "pressure"]
        assert len({c.message for c in neutral}) == 1
        assert {c.context_variant for c in variants} == set(continuity_cases.CONTEXTS)
    assert (
        len({from_actor(matrix_cases.actors(v[0])[0]).model_dump_json() for v in groups.values()})
        == 3
    )
    plan = matrix_cli.manifest(cases, max_output_tokens=4096)
    assert plan["max_logical_calls"] == 105
    assert plan["output_token_override"] == 4096


def test_relationship_changes_are_sourced_reports_and_urgency_is_a_public_event():
    cases = {c.context_variant: c for c in continuity_cases.catalogue() if c.persona == "reserved"}
    assert "five inspections" in cases["familiar"].history_text(0, "npc-01")
    assert "despite my objection" in cases["breach"].history_text(0, "npc-01")
    assert cases["routine"].history_text(0, "npc-01") == cases["urgent"].history_text(0, "npc-01")
    assert cases["urgent"].observed_event and not cases["routine"].observed_event
    assert "No supervisory authority" in cases["pressure"].scene


@pytest.mark.parametrize("fixture", continuity_cases.catalogue(), ids=lambda case: case.id)
async def test_continuity_fixtures_use_reviewed_commit_and_retain_identity(fixture):
    result = await matrix_runner.run(fixture, Models())
    assert result["status"] == "ok", result["error"]
    assert result["identity_unchanged"] and result["inactive_unchanged"]
    assert result["psychological_quality"].startswith("unrated")


async def test_batch_stops_after_unconfirmed_transport_and_reports_partial_completion(
    monkeypatch, tmp_path
):
    from backend.engine.chpm.evaluation import configuration, storage

    monkeypatch.setattr(storage, "ROOT", tmp_path)
    calls = []

    async def factory(*args, **kwargs):
        return Models()

    async def run(fixture, model, **kwargs):
        calls.append(fixture.id)
        return {"status": "failed", "calls": [{"status": "failed"}]}

    monkeypatch.setattr(configuration, "factory_for", factory)
    monkeypatch.setattr(matrix_runner, "run", run)
    args = SimpleNamespace(
        all_present=False,
        max_total_calls=14,
        output_tokens=4096,
        run_id="offline",
        user=None,
        endpoint="unused",
        model="unused",
        timeout=30,
    )
    await matrix_cli.execute(args, continuity_cases.catalogue()[:2])
    summary = json.loads((tmp_path / "offline" / "summary.json").read_text())
    assert len(calls) == summary["completed"] == 1
    assert summary["planned"] == 2
