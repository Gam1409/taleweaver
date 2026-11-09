"""Shared state extraction keeps its safe operation and phase in diagnostic events."""

import pytest

from backend.core.diagnostic_fields import safe_fields
from backend.core.llm_diagnostics import _purpose


@pytest.mark.parametrize(
    "operation", ["narrated_items", "scene_staging", "rp_continuation", "regenerate_narration"]
)
def test_metadata_only_reconciliation_purposes_are_retained(operation):
    expected = {"purpose": operation, "phase": "reconciliation"}
    assert _purpose({"operation": operation, "phase": "reconciliation"}) == expected
    assert safe_fields(expected) == expected


def test_free_text_is_still_excluded_from_diagnostic_metadata():
    assert _purpose({"operation": "PRIVATE_STORY_TEXT", "phase": "PRIVATE_STORY_TEXT"}) == {}
    assert "purpose" not in safe_fields({"purpose": "PRIVATE_STORY_TEXT"})


@pytest.mark.parametrize(
    "operation,phase",
    [
        ("wardrobe_recovery", "preview"),
        ("wardrobe_recovery", "schema_retry"),
        ("wardrobe_recovery", "evidence_retry"),
        ("item_repair", "preview"),
        ("chpm", "agent_lookup"),
        ("chpm", "repair"),
        ("rp_continuation", "rp_continuation"),
        ("living_world_decision", "decision"),
        ("living_world_dialogue_choice", "decision"),
        ("chpm_evaluation", "proposal"),
    ],
)
def test_known_recovery_and_decision_stages_are_not_silently_discarded(operation, phase):
    expected = {"purpose": operation, "phase": phase}
    assert _purpose({"operation": operation, "phase": phase}) == expected
    assert safe_fields(expected) == expected
