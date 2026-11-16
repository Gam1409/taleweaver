"""A shared English plan produces all formats with mechanically checked provenance."""

from copy import deepcopy

import pytest

from backend.core.image_prompt_rules import ImagePromptRules
from backend.engine.scene_illustrations.plan_preparation import normalization_key
from backend.engine.scene_illustrations.prompt_compiler import (
    EnglishPlan,
    compile_plan,
    final_source_map,
    validate_plan,
)
from backend.engine.scene_illustrations.visual_plan import inventory
from tests.test_visual_plan import proposal_for, scene


def english_plan_for(atoms):
    description = proposal_for(atoms)
    tags = proposal_for(atoms, "tags")
    return EnglishPlan(
        facts=[
            {
                **left.model_dump(exclude={"text", "section", "disposition"}),
                "description": {"text": left.text},
                "tags": {"text": right.text},
            }
            for left, right in zip(description.units, tags.units, strict=True)
        ]
    )


@pytest.mark.parametrize("output_format", ["description", "tags", "hybrid"])
@pytest.mark.parametrize("name", ["Emiral", "Эмираль", "Émilie", "ミキ", "Łukasz", "Jürgen"])
def test_all_formats_preserve_bindings_and_offsets(name, output_format):
    facts = scene()
    facts["characters"][0]["name"] = name
    facts["lighting"] = "Soft daylight"
    atoms = inventory(facts)
    plan = english_plan_for(atoms)
    original = deepcopy(plan)
    compiled = compile_plan(atoms, plan, output_format)
    assert plan == original
    assert {u.atom_id for u in compiled["proposal"].units} == {a.id for a in atoms}
    by_id = {u.atom_id: u for u in compiled["proposal"].units}
    for row in compiled["source_map"]:
        if row["start"] is not None:
            assert compiled["body"][row["start"] : row["end"]] == by_id[row["atom_id"]].text
    assert len(compiled["source_map"]) == len(atoms)
    if output_format == "hybrid":
        assert {u.section for u in compiled["proposal"].units} == {"tags", "description"}
        required = {a.id for a in atoms if a.required}
        assert all(
            u.section == "description" for u in compiled["proposal"].units if u.atom_id in required
        )


def test_unused_tag_variant_cannot_smuggle_a_missing_fact():
    atoms = inventory(scene())
    plan = english_plan_for(atoms)
    plan.facts[1].tags.text = ""
    with pytest.raises(ValueError):
        compile_plan(atoms, plan, "description")


def test_swapped_bindings_or_value_hash_fail_in_shared_plan():
    atoms = inventory(scene())
    for field, value in [("subject", "b"), ("target", "invented"), ("value_hash", "0" * 64)]:
        plan = english_plan_for(atoms)
        setattr(plan.facts[0], field, value)
        with pytest.raises(ValueError):
            validate_plan(atoms, plan)


def test_unsupported_tag_relation_does_not_destroy_prose():
    atoms = inventory(scene())
    plan = english_plan_for(atoms)
    relation = next(f for f in plan.facts if f.predicate == "placement")
    relation.tags.text = ""
    relation.tags.disposition = "tag_binding"
    tags = compile_plan(atoms, plan, "tags")
    prose = compile_plan(atoms, plan, "description")
    hybrid = compile_plan(atoms, plan, "hybrid")
    assert any(
        row["atom_id"] == relation.atom_id and row["start"] is None for row in tags["source_map"]
    )
    assert any(
        row["atom_id"] == relation.atom_id and row["start"] is not None
        for row in prose["source_map"]
    )
    assert any(
        row["atom_id"] == relation.atom_id and row["start"] is not None
        for row in hybrid["source_map"]
    )


def test_source_map_handles_repeated_text_prefixes_and_unicode():
    atoms = inventory(scene())
    plan = english_plan_for(atoms)
    for fact in plan.facts:
        fact.description.text = "🪑 Same text."
    compiled = compile_plan(atoms, plan, "description")
    positive = "✨ Style. " + compiled["body"] + " Quality."
    provenance = final_source_map(compiled["body"], positive, compiled["source_map"])
    assert provenance["final_mapping"] == "exact"
    for row in provenance["facts"]:
        assert positive[row["positive_start"] : row["positive_end"]] == "🪑 Same text."
    ambiguous = final_source_map(compiled["body"], compiled["body"] * 2, compiled["source_map"])
    assert ambiguous["final_mapping"] == "unavailable"
    assert all(row["positive_start"] is None for row in ambiguous["facts"])


def test_compatible_format_changes_reuse_normalization_key():
    request = {"provider_options": {"_prompt_user": None}}
    keys = [
        normalization_key(request, ImagePromptRules(format=fmt, instructions="Shared vocabulary"))
        for fmt in ("description", "tags", "hybrid")
    ]
    assert len(set(keys)) == 1
    assert (
        normalization_key(request, ImagePromptRules(instructions="Different vocabulary")) != keys[0]
    )
    assert normalization_key(request, ImagePromptRules(max_words=200)) != keys[0]
