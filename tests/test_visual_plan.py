"""Coverage checks bind actual output units, without requiring source-language words."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.image_prompt_rules import ImagePromptRules
from backend.engine.scene_illustrations import plan_preparation as preparation
from backend.engine.scene_illustrations.plan_artifact import artifact, verify_media, verify_texts
from backend.engine.scene_illustrations.visual_plan import (
    Audit,
    Proposal,
    assemble,
    fingerprint,
    inventory,
)
from backend.engine.visual_plan_lifecycle import KEY, prune, reset, without_cache


def scene():
    return {
        "characters": [
            {
                "id": "a",
                "name": "Эмираль",
                "posture": "sitting",
                "clothing_tokens": ["синий плащ"],
                "placement": {
                    "relation": "on",
                    "target_kind": "scene_object",
                    "target": "скамейка",
                },
            },
            {
                "id": "b",
                "name": "ミキ",
                "posture": "standing",
                "placement": {"relation": "in_front_of", "target_kind": "character", "target": "a"},
            },
        ],
        "props": [
            {"item_id": "coat", "owner_id": "b", "name": "пальто", "spatial_position": "на полу"}
        ],
    }


def proposal_for(atoms, format="description"):
    return Proposal(
        units=[
            {
                "atom_id": a.id,
                "subject": a.subject,
                "predicate": a.predicate,
                "target": a.target,
                "value_hash": fingerprint(a.value),
                "text": f"English realization {i}",
                "section": format,
            }
            for i, a in enumerate(atoms)
        ]
    )


@pytest.mark.parametrize("format", ["description", "tags", "hybrid"])
def test_multilingual_units_and_formats(format):
    atoms = inventory(scene())
    proposal = proposal_for(atoms, "tags" if format == "tags" else "description")
    if format == "hybrid":
        proposal.units[-1].section = "tags"
    body, limits = assemble(atoms, proposal, format)
    assert "Эмираль" not in body
    assert "English realization" in body
    assert bool(limits) == (format == "tags")
    assert scene()["characters"][0]["name"] == "Эмираль"


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "subject", "target", "predicate", "value", "disposition", "section"],
)
def test_swaps_and_losses_fail_structural_validation(mutation):
    atoms = inventory(scene())
    proposal = proposal_for(atoms)
    unit = next(u for u in proposal.units if u.predicate == "placement")
    if mutation == "missing":
        proposal.units.pop()
    elif mutation == "duplicate":
        proposal.units.append(proposal.units[0])
    elif mutation == "value":
        unit.value_hash = "0" * 64
    elif mutation == "disposition":
        unit.text, unit.disposition = "", "best_effort"
    elif mutation == "section":
        unit.section = "tags"
    else:
        setattr(unit, mutation, "different")
    with pytest.raises(ValueError):
        assemble(atoms, proposal, "description")


def test_count_tags_do_not_invent_gender_and_limits_are_explicit():
    atoms = inventory(scene())
    proposal = proposal_for(atoms, "tags")
    count = proposal.units[0]
    count.text, count.disposition = "", "implicit_count"
    placement = next(u for u in proposal.units if u.predicate == "placement")
    placement.text, placement.disposition = "", "tag_binding"
    _, limits = assemble(atoms, proposal, "tags")
    assert {limit["reason"] for limit in limits} >= {
        "implicit_count",
        "tag_binding",
        "global_tag_binding",
    }


def test_missing_clothing_is_unknown_and_invalid_source_is_rejected():
    atoms = inventory({"characters": [{"id": "a", "managed_clothing": True}]})
    assert any(a.predicate == "clothing_unknown" for a in atoms)
    assert not any(a.predicate == "worn" for a in atoms)
    with pytest.raises(ValueError):
        inventory({"characters": "bad"})
    facts = scene()
    facts["characters"][1]["placement"]["target"] = "absent"
    with pytest.raises(ValueError):
        inventory(facts)


@pytest.mark.asyncio
async def test_structural_retry_is_bounded(monkeypatch):
    call = AsyncMock(return_value=Proposal(units=[]))
    monkeypatch.setattr(preparation, "_call", call)
    with pytest.raises(ValueError, match="after a retry"):
        await preparation.normalize(None, inventory(scene()), ImagePromptRules())
    assert call.await_count == 2
    assert "repair" in call.call_args.args[2]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result,status",
    [
        (
            Audit(status="passed", issues=[{"atom_id": "artifact", "reason": "contradiction"}]),
            "inconclusive",
        ),
        (
            Audit(status="failed", issues=[{"atom_id": "foreign", "reason": "omission"}]),
            "inconclusive",
        ),
        (TimeoutError(), "unavailable"),
    ],
)
async def test_audit_never_certifies_malformed_or_unavailable_results(monkeypatch, result, status):
    call = (
        AsyncMock(side_effect=result)
        if isinstance(result, Exception)
        else AsyncMock(return_value=result)
    )
    monkeypatch.setattr(preparation, "_call", call)
    atoms = inventory(scene())
    actual = await preparation.audit(
        None, atoms, proposal_for(atoms), {"positive": "test", "negative": "none"}, []
    )
    assert actual["status"] == status


@pytest.mark.asyncio
async def test_actual_media_text_is_fenced():
    request = {
        "provider": "stable_diffusion",
        "provider_options": {"negative_prompt": "blur"},
        "style_instruction": "watercolor",
    }
    texts = await artifact(request, "Two people by a bench.")
    options = {
        **request["provider_options"],
        "_visual_plan_artifact": texts,
        "_visual_plan_provider": "stable_diffusion",
    }
    verify_media(texts["positive"], options)
    with pytest.raises(ValueError):
        verify_media(texts["positive"] + " A third person.", options)
    with pytest.raises(ValueError):
        verify_texts(texts["positive"], "two people", options)


def test_profile_key_seed_reuse_and_format_invalidation():
    request = {
        "provider": "stable_diffusion",
        "model": "one",
        "provider_options": {"seed": 42, "_prompt_user": SimpleNamespace(llm_settings={})},
    }
    first = preparation.profile_key(request, ImagePromptRules())
    request["provider_options"]["seed"] = 43
    assert preparation.profile_key(request, ImagePromptRules()) == first
    assert preparation.profile_key(request, ImagePromptRules(format="tags")) != first
    request["model"] = "two"
    assert preparation.profile_key(request, ImagePromptRules()) != first


def test_lifecycle_discards_derived_data_and_changes_epoch():
    states = reset({"npc": {"name": "Miki"}})
    old = deepcopy(states)
    assert reset(states)[KEY]["epoch"] != states[KEY]["epoch"]
    assert without_cache(states) == {"npc": {"name": "Miki"}}
    states[KEY]["entries"] = {"keep": {"message_id": "1"}, "drop": {"message_id": "2"}}
    prune(states, {"1"})
    assert set(states[KEY]["entries"]) == {"keep"}
    assert old["npc"] == states["npc"]


def test_nsfw_routes_to_legacy_without_changing_its_prompts():
    with pytest.raises(ValueError, match="Current preparation"):
        preparation.policy_for(
            {"provider": "stable_diffusion", "provider_options": {"_nsfw_enabled": True}}
        )


@pytest.mark.asyncio
async def test_comfy_final_prefix_suffix_are_audited_and_mutations_block(monkeypatch, tmp_path):
    from backend.core.comfyui_config import ComfyWorkflow
    from backend.core.config import settings
    from backend.engine.comfyui_client import ComfyClient
    from backend.engine.comfyui_images import generate_comfy_image

    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    workflow = {
        "name": "Bound text",
        "graph": {
            "text": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
            "save": {"class_type": "SaveImage", "inputs": {}},
        },
        "bindings": {"prompt": {"node_id": "text", "input_name": "text"}},
        "output_node": "save",
    }
    options = {
        "comfyui_url": "http://127.0.0.1:8188",
        "comfyui_assignments": {"simple": "test"},
        "comfyui_presets": {
            "test": {
                "name": "Test",
                "generate": workflow,
                "prompt_rules": {"prefix": "watercolor", "suffix": "three people"},
            }
        },
        "_prompt_prepared": True,
    }
    request = {"provider": "comfyui", "provider_options": options}
    texts = await artifact(request, "Two people.")
    assert texts["positive"] == "watercolor Two people. three people"
    call = AsyncMock(
        return_value=Audit(
            status="failed", issues=[{"atom_id": "artifact", "reason": "contradiction"}]
        )
    )
    monkeypatch.setattr(preparation, "_call", call)
    atoms = inventory(scene())
    result = await preparation.audit(None, atoms, proposal_for(atoms), texts, [])
    assert result["status"] == "failed"
    assert call.call_args.args[2]["positive"] == texts["positive"]
    options["_visual_plan_artifact"] = texts
    original = ComfyWorkflow.render

    def mutated(self, values):
        graph = original(self, values)
        graph["text"]["inputs"]["text"] += " changed after audit"
        return graph

    monkeypatch.setattr(ComfyWorkflow, "render", mutated)
    execute = AsyncMock()
    monkeypatch.setattr(ComfyClient, "execute", execute)
    with pytest.raises(ValueError, match="differs from its audited artifact"):
        await generate_comfy_image("Two people.", options, str(tmp_path), "unused.png")
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_100_renders_are_byte_identical_without_language_model_calls(monkeypatch):
    call = AsyncMock(side_effect=AssertionError("No adaptation after freezing"))
    from backend.engine import image_prompt_adapter

    monkeypatch.setattr(image_prompt_adapter, "adapt_body", call)
    request = {"provider": "stable_diffusion", "provider_options": {"seed": 0}}
    first = await artifact(request, "Emiral sits on a bench. Miki stands in front of him.")
    for seed in range(100):
        request["provider_options"]["seed"] = seed
        assert await artifact(request, first["body"]) == first
    call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openrouter", "black_forest_labs"])
async def test_unused_negative_text_does_not_influence_audit(provider):
    request = {"provider": provider, "provider_options": {"negative_prompt": "not submitted"}}
    texts = await artifact(request, "A person.")
    assert texts["negative"] == ""
    verify_media(
        texts["positive"],
        {
            **request["provider_options"],
            "_visual_plan_artifact": texts,
            "_visual_plan_provider": provider,
        },
    )


def test_preference_aba_has_a_fresh_epoch():
    from backend.engine.visual_novel.config import VnSettings, write_settings

    state = SimpleNamespace(entity_states={})
    write_settings(state, VnSettings(visual_preparation="plan"))
    first = state.entity_states[KEY]["epoch"]
    write_settings(state, VnSettings())
    write_settings(state, VnSettings(visual_preparation="plan"))
    assert state.entity_states[KEY]["epoch"] != first
