"""One preset recipe per image task and supported model family, built on demand."""

from typing import Any

from backend.core.comfyui_config import ComfyPreset
from backend.core.comfyui_starter_models import (
    FAMILIES,
    LoaderRecipe,
    default_recipe,
    recipe_label,
    resolved_recipe,
)
from backend.core.comfyui_starters import starter_workflow
from backend.core.image_prompt_templates import template_rules
from backend.core.image_purposes import ImagePurpose, purpose_target
from backend.core.visual_limits import visual_limits

TASKS = {
    "npc": (
        "NPC portrait",
        "Frame one character in a readable portrait. Preserve established appearance and clothing; keep the background secondary.",
        "An adult traveler in a blue coat, waist-up portrait, simple backdrop",
        "1person, solo, blue coat, waist up, simple background",
    ),
    "protagonist": (
        "Hero portrait",
        "Frame the protagonist alone as a character portrait. Preserve identity and current clothing; do not invent equipment.",
        "An adult explorer in a green jacket, character portrait, simple backdrop",
        "1person, solo, green jacket, character portrait, simple background",
    ),
    "avatar": (
        "Account avatar",
        "Create a clear single-person profile portrait with a simple background and a centered face.",
        "An adult storyteller, centered face portrait, soft neutral background",
        "1person, solo, portrait, centered face, simple background",
    ),
    "object": (
        "Inventory item",
        "Show the supplied object clearly as an isolated inventory asset. Avoid hands, people, labels and UI frames unless explicitly requested.",
        "One brass lantern, isolated object, neutral background, clear silhouette",
        "brass lantern, single object, isolated, simple background, no humans",
    ),
    "background": (
        "Location background",
        "Show the environment as a wide background. Do not add characters unless the supplied location explicitly calls for them.",
        "An empty stone courtyard at dawn, wide view, soft light",
        "stone courtyard, dawn, scenery, wide shot, no humans",
    ),
    "illustration": (
        "Story illustration",
        "Depict the supplied story moment. Preserve character count, relative positions and actions; do not replace the scene with an isolated portrait.",
        "An adult traveler sits on a bench while an adult guard stands on the ground facing the traveler, wide scene",
        "2people, traveler sitting on bench, guard standing on ground facing traveler, wide shot, courtyard",
    ),
    "cover": (
        "Adventure cover",
        "Compose a wide cinematic cover from the adventure's actual setting and subjects. Avoid generated titles, letters and logos unless requested.",
        "A distant castle above a misty valley, panoramic cinematic composition",
        "castle, misty valley, panoramic view, cinematic composition, scenery",
    ),
    "catalog": (
        "Style preview",
        "Illustrate the requested style or tone in a clean square preview. Do not add interface elements, captions or lettering.",
        "A woodland cottage beside a path, balanced square composition",
        "woodland cottage, path, scenery, balanced composition",
    ),
}


def template_dimensions(family: str, purpose: str, multiple: int) -> tuple[int, int]:
    bounds = visual_limits(purpose_target(purpose))
    edge = 512 if family == "sd15" else 1024
    scale = min(1.0, edge / max(bounds["maxWidth"], bounds["maxHeight"]))
    width = max(multiple, int(bounds["maxWidth"] * scale) // multiple * multiple)
    height = max(multiple, int(bounds["maxHeight"] * scale) // multiple * multiple)
    return width, height


def preset_catalog() -> list[dict[str, Any]]:
    return [_entry(family, purpose) for family in FAMILIES for purpose in TASKS]


def _entry(family: str, purpose: str) -> dict[str, Any]:
    spec = FAMILIES[family]
    return {
        "id": f"{family}:{purpose}",
        "family": family,
        "family_name": spec["name"],
        "purpose": purpose,
        "name": f"{TASKS[purpose][0]} · {spec['name']}",
        "defaults": default_recipe(family),
        "layouts": ["checkpoint", "diffusion"] if "diffusion" in spec else ["checkpoint"],
        "custom_checkpoint_required": "checkpoint" not in spec,
        "reference_available": purpose not in ("avatar", "catalog"),
        "limits": visual_limits(purpose_target(purpose)),
        "sources": spec["sources"],
        "notes": "Base model only: no distilled/Turbo, Edit, GGUF or LoRA variant is assumed. "
        "Embedded components must actually exist in your checkpoint. Server filenames cannot prove this. "
        "The optional reference variant is img2img, not identity conditioning.",
    }


def task_preset(family: str, purpose: ImagePurpose, recipe: LoaderRecipe | None = None) -> dict:
    if family not in FAMILIES or purpose not in TASKS:
        raise ValueError("Unknown model family or image task.")
    entry = _entry(family, purpose)
    chosen = resolved_recipe(family, recipe)
    label = recipe_label(chosen)
    rules = template_rules(family)
    task = TASKS[purpose]
    rules.instructions = f"{rules.instructions}\nTask composition: {task[1]}"
    example = task[3] if rules.format == "tags" else task[2]
    generate = starter_workflow(family, recipe=recipe)
    reference = (
        starter_workflow(family, True, recipe=recipe) if entry["reference_available"] else None
    )
    width, height = template_dimensions(family, purpose, generate.dimension_multiple)
    for workflow in (generate, reference):
        if workflow is None:
            continue
        mode = "With reference (img2img)" if "image" in workflow.bindings else "No reference"
        workflow.name = f"{entry['name']} · {mode} · {label}"
        workflow.graph = workflow.render(
            {
                "width": width,
                "height": height,
                "prompt": example,
                "negative_prompt": rules.negative_prompt,
            }
        )
    preset = ComfyPreset(
        name=f"{entry['name']} · {label}",
        generate=generate,
        reference=reference,
        prompt_rules=rules,
        auto_prompt_template=False,
        purpose_tags=[purpose],
    )
    return {
        "preset": preset.model_dump(),
        "recipe": chosen,
        "sources": entry["sources"],
        "notes": entry["notes"],
        "dimensions": {"width": width, "height": height},
    }
