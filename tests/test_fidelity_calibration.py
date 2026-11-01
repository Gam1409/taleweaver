"""Literal verification must respect English adaptation and tag-oriented checkpoints."""

from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core import reliability_metrics
from backend.core.image_prompt_rules import ImagePromptRules
from backend.engine.scene_illustrations import fidelity, render
from backend.engine.scene_staging.schema import SceneExtraction
from backend.engine.scene_staging.state import reconcile

FACTS = {
    "characters": [
        {"id": "e", "name": "Эмирал", "clothing_tokens": ["синий плащ"]},
        {
            "id": "m",
            "name": "Miki",
            "placement": {
                "target_kind": "scene_object",
                "target": "на дальнем углу",
            },
        },
    ],
    "props": [{"name": "Книга", "spatial_position": "на столе"}],
}


def test_translated_source_does_not_require_cyrillic_literals():
    assert fidelity.anchors(FACTS) == ["Miki"]
    assert (
        fidelity.literal_diff(
            "2 people. Emiral wears a blue cloak. Miki stands at the far corner; a book is on the table.",
            FACTS,
        )
        == []
    )
    contract = fidelity.requirements(FACTS)
    assert "на дальнем углу" not in contract
    assert "Translate non-Latin" in contract
    assert fidelity.literal_diff("2 people. Emiral waits.", FACTS) == ["Miki"]


@pytest.mark.parametrize(
    "name,expected", [("Émilie", True), ("Miki-美紀", False), ("李", False), ("Лина", False)]
)
def test_anchor_script_detection(name, expected):
    assert bool(fidelity.anchors({"characters": [{"name": name}]})) is expected


@pytest.mark.parametrize(
    "tags,count,valid",
    [
        ("1boy, 1girl", 2, True),
        ("2girls, 1boy", 3, True),
        ("2girls", 1, False),
        ("solo", 1, True),
        ("solo", 2, False),
        ("1boy, 1girl, 2 people", 2, True),
        ("1boy, 1girl, 3 people", 2, False),
        ("group, standing", 2, True),
        ("1girl, 1girl", 1, True),
    ],
)
def test_tag_counts_are_optional_but_explicit_counts_must_match(tags, count, valid):
    facts = {"characters": [{} for _ in range(count)]}
    assert bool(fidelity.literal_diff(tags, facts, prompt_format="tags")) is not valid


@pytest.mark.parametrize("prompt_format", ["description", "hybrid"])
def test_prose_count_is_still_required(prompt_format):
    assert fidelity.literal_diff("Miki waits.", FACTS, prompt_format=prompt_format) == ["2 people"]


async def test_russian_tag_scene_renders_without_retry_or_prose_count(monkeypatch):
    adapted = AsyncMock(return_value="1boy, 1girl, Emiral, Miki, blue cloak, book on table")
    monkeypatch.setattr(render, "adapt_body", adapted)
    monkeypatch.setattr(render, "prompt_rules", lambda _: ImagePromptRules(format="tags"))
    monkeypatch.setattr(render, "select_profile", lambda _: SimpleNamespace(mature_themes=False))
    request = {
        "prompt": "Сцена с книгой на столе",
        "provider": "comfyui",
        "provider_options": {"_prompt_user": object()},
        "_scene_facts": FACTS,
    }
    await render.prepare_moment_prompt(request)
    assert adapted.await_count == 1
    assert request["provider_options"]["_prompt_prepared"]
    policy = adapted.call_args.args[1]
    assert policy.language == "English" and policy.format == "tags"
    assert "Include '2 people'" not in policy.instructions
    assert adapted.call_args.args[0] == "Сцена с книгой на столе"


def test_single_character_scenes_do_not_require_a_count_phrase():
    facts = {"characters": [{"name": "Lina", "clothing_tokens": ["Red coat"]}]}
    assert fidelity.literal_diff("Lina in a Red coat, a lone figure at the window.", facts) == []
    contract = fidelity.requirements(facts)
    assert "1 people" not in contract
    # Two-character scenes still enforce the declared prose count.
    assert fidelity.literal_diff("Lina and Miki wait.", FACTS) == ["2 people"]


def test_staging_counters_expose_rejected_delta_and_whole_turn_reset(monkeypatch):
    monkeypatch.setattr(reliability_metrics, "_staging", Counter())
    state = SimpleNamespace(current_scene_id="room", entity_states={})
    extraction = SceneExtraction(
        changes=[
            {"entity_id": "e", "posture": "standing", "evidence": "Emiral stands."},
            {"entity_id": "m", "posture": "sitting", "evidence": "An invented quote."},
        ]
    )
    result = reconcile(state, FACTS["characters"], "Emiral stands.", extraction)
    assert result["rejected"] == 1 and result["actors"] == {}
    reliability_metrics.record_staging(result, len(extraction.changes))
    reliability_metrics.record_staging({"status": "ready", "rejected": 0}, 0)
    assert reliability_metrics.snapshot()["staging"] == {
        "reconciliations": 2,
        "proposed_deltas": 2,
        "rejected_deltas": 1,
        "fail_closed_turns": 1,
        "ready_turns": 1,
    }


@pytest.mark.parametrize("prompt_format", ["description", "hybrid"])
@pytest.mark.parametrize(
    "phrase,valid",
    [
        ("a lone figure", True),
        ("1 person", True),
        ("2 people", False),
        ("0 people", False),
        ("1 person and 2 people", False),
    ],
)
def test_solo_prose_allows_missing_count_but_rejects_contradictions(prompt_format, phrase, valid):
    facts = {"characters": [{"name": "Lina"}]}
    assert (
        bool(
            fidelity.literal_diff(
                f"Lina at the window, {phrase}.", facts, prompt_format=prompt_format
            )
        )
        is not valid
    )


@pytest.mark.parametrize("prompt_format", ["description", "hybrid"])
def test_empty_scene_rejects_explicit_people(prompt_format):
    assert fidelity.literal_diff(
        "2 people at the window.", {"characters": []}, prompt_format=prompt_format
    )
