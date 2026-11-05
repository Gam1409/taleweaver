"""Stress fixtures exercise real recall windows without calling a model server."""

import json

import pytest

from backend.engine.chpm import appraisal_context
from backend.engine.chpm.evaluation import (
    matrix_cases,
    matrix_history,
    matrix_runner,
    memory_stress,
)
from tests.test_chpm_matrix import Models


def window(case_id):
    case = next(case for case in memory_stress.catalogue() if case.id == case_id)
    actor = matrix_cases.actors(case)[0]
    mind = matrix_history.seed(case, actor, "stress")
    return appraisal_context.build(mind, query=case.message), mind


def test_old_literal_cue_recalls_original_source_outside_recent_window():
    view, mind = window("recall-exact-h40")
    recalled = [source for alias, (_, source, _) in view.sources.items() if alias.startswith("r")]
    assert any(source.message_id == "old-reply-2" for source in recalled)
    assert memory_stress.OLD_FACT in json.dumps(view.payload)
    assert len(mind.sources) == 80


def test_lexical_paraphrase_miss_is_visible_not_mislabelled_semantic_recall():
    view, _ = window("recall-paraphrase-h40")
    assert memory_stress.OLD_FACT not in json.dumps(view.payload)
    assert view.payload["episodic_recall"]["retrieval_mode"] == "lexical"


def test_new_and_old_conflicting_accounts_remain_distinguishable():
    view, _ = window("recall-superseded-h40")
    assert any(source.text == memory_stress.NEW_FACT for _, source, _ in view.sources.values())
    assert any(source.text == memory_stress.OLD_FACT for _, source, _ in view.sources.values())
    historical = {item["source_id"] for item in view.payload["recollected_episodes"]}
    assert all(view.sources[key][1].text != memory_stress.NEW_FACT for key in historical)


def test_dense_history_preserves_unfinished_actions_and_ownership():
    view, _ = window("dense-actions-h3")
    text = json.dumps(view.payload)
    assert "kept the receipt, not the parcel" in text
    assert "have not signed or sent it" in text
    assert "remains locked away" in text


@pytest.mark.asyncio
async def test_stress_run_records_actual_proposal_memory_and_perception():
    case = matrix_cases.choose("stress", ["recall-exact-h40"])[0]
    result = await matrix_runner.run(case, Models())
    assert result["status"] == "ok", result["error"]
    assert "npc-01" in result["perceptions"]
    call = next(call for call in result["calls"] if call["phase"] == "proposal")
    assert memory_stress.OLD_FACT in json.dumps(call["context_audit"])
    assert call["context_audit"]["context_packing"]["canonical_history_changed"] is False
