"""Purpose-specific workflows preserve legacy fallback and story overrides."""

from types import SimpleNamespace

import pytest

from backend.core.comfyui_config import ComfySettings, select_profile
from backend.core.image_purposes import PURPOSES, image_provider
from backend.engine.story_visual_presets import story_t2i
from tests.test_comfyui import workflow
from tests.test_comfyui_presets import named_preset

__all__ = ["workflow"]


@pytest.fixture
def options(workflow):
    return {
        "simple_model_provider": "openai",
        "advanced_model_provider": "openai",
        "comfyui_presets": {
            "legacy": named_preset(workflow),
            "special": {**named_preset(workflow), "name": "Special"},
        },
        "comfyui_assignments": {"simple": "legacy", "advanced": "legacy"},
    }


@pytest.mark.parametrize("purpose", sorted(PURPOSES))
def test_task_assignment_selects_workflow_and_provider(options, purpose):
    options["comfyui_assignments"][purpose] = "special"
    assert image_provider(options, "simple", purpose) == "comfyui"
    assert select_profile({**options, "image_purpose": purpose}).name == "Special"
    assert image_provider(options, "simple", "unassigned") == "openai"
    assert select_profile(options).name == "Illustrations"


def test_background_and_moment_are_independent(options):
    options["comfyui_assignments"]["background"] = "special"
    assert select_profile({**options, "image_purpose": "background"}).name == "Special"
    assert select_profile({**options, "image_purpose": "illustration"}).name == "Illustrations"


def test_legacy_story_override_keeps_priority_over_global_tasks(options):
    options["comfyui_assignments"]["background"] = "special"
    story = SimpleNamespace(original_manifest={"visual_presets": {"advanced": "legacy"}})
    resolved = story_t2i(options, story)
    assert resolved["comfyui_assignments"]["background"] == "legacy"
    assert options["comfyui_assignments"]["background"] == "special"


def test_explicit_story_task_wins_and_current_source_ignores_it(options):
    manifest = {"visual_presets": {"advanced": "legacy", "background": "special"}}
    story = SimpleNamespace(original_manifest=manifest)
    assert story_t2i(options, story)["comfyui_assignments"]["background"] == "special"
    manifest["visual_preset_source"] = "current"
    assert "background" not in story_t2i(options, story)["comfyui_assignments"]


def test_library_tags_round_trip(options):
    options["comfyui_presets"]["special"].update(
        purpose_tags=["background", "illustration"], style_tags=["gothic", "monochrome"]
    )
    saved = ComfySettings.model_validate(options).model_dump()
    assert saved["comfyui_presets"]["special"]["style_tags"] == ["gothic", "monochrome"]
    assert saved["comfyui_presets"]["special"]["purpose_tags"] == ["background", "illustration"]
