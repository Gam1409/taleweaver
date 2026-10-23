"""Typed, bounded API-workflow settings for the ComfyUI image provider."""

import copy
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.core.image_prompt_rules import ImagePromptRules
from backend.utils.path_security import validate_provider_url

BindingName = Literal["prompt", "negative_prompt", "seed", "width", "height", "image"]


class WorkflowBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(min_length=1, max_length=120)
    input_name: str = Field(min_length=1, max_length=120)


class ComfyWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Workflow", min_length=1, max_length=120)
    graph: dict[str, Any]
    bindings: dict[BindingName, WorkflowBinding]
    output_node: str
    dimension_multiple: Literal[8, 16, 32, 64] = 8

    @model_validator(mode="after")
    def validate_graph(self) -> "ComfyWorkflow":
        if not self.graph or len(self.graph) > 256:
            raise ValueError("An API workflow must contain 1 to 256 nodes.")
        if len(json.dumps(self.graph).encode()) > 262144:
            raise ValueError("Workflow exceeds the 256 KiB limit.")
        for node in self.graph.values():
            if not isinstance(node, dict) or not isinstance(node.get("class_type"), str):
                raise ValueError("Use ComfyUI API export, not the editor workflow JSON.")
            if not isinstance(node.get("inputs"), dict):
                raise ValueError("Every API node must have an inputs object.")
        if "prompt" not in self.bindings or self.output_node not in self.graph:
            raise ValueError("Select the prompt input and an existing output node.")
        targets = [(b.node_id, b.input_name) for b in self.bindings.values()]
        if len(targets) != len(set(targets)):
            raise ValueError("Different bindings cannot overwrite the same input.")
        for name, binding in self.bindings.items():
            self._validate_binding(name, binding)
        return self

    def _validate_binding(self, name: str, binding: WorkflowBinding) -> None:
        node = self.graph.get(binding.node_id, {})
        inputs = node.get("inputs", {})
        if binding.input_name not in inputs:
            raise ValueError(f"Binding input missing: {binding.node_id}.{binding.input_name}")
        if isinstance(inputs[binding.input_name], (list, dict)):
            raise ValueError("Bind a literal input, not a connected socket.")
        value = inputs[binding.input_name]
        expected = str if name in ("prompt", "negative_prompt", "image") else int
        if not isinstance(value, expected) or isinstance(value, bool):
            raise ValueError(f"The {name} binding has the wrong input type.")

    def render(self, values: dict[str, Any]) -> dict[str, Any]:
        graph = copy.deepcopy(self.graph)
        for key, binding in self.bindings.items():
            if key in values and values[key] is not None:
                graph[binding.node_id]["inputs"][binding.input_name] = values[key]
        return graph


class ComfyProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generate: ComfyWorkflow | None = None
    reference: ComfyWorkflow | None = None

    @model_validator(mode="after")
    def validate_image_input(self) -> "ComfyProfile":
        if self.generate and "image" in self.generate.bindings:
            raise ValueError("Use the image workflow slot for an image binding.")
        if self.reference and "image" not in self.reference.bindings:
            raise ValueError("The image workflow requires an image binding.")
        return self


class ComfyPreset(ComfyProfile):
    name: str = Field(min_length=1, max_length=120)
    prompt_rules: ImagePromptRules | None = None
    auto_prompt_template: bool = False
    mature_themes: bool = False

    @model_validator(mode="after")
    def choose_template(self) -> "ComfyPreset":
        from backend.core.image_model_detection import detect_preset_template
        from backend.core.image_prompt_templates import template_rules

        if self.auto_prompt_template:
            detected = detect_preset_template(
                self.generate.graph if self.generate else {},
                self.reference.graph if self.reference else None,
            )
            self.prompt_rules = (
                template_rules(detected["template_id"]) if detected["template_id"] else None
            )
        return self


class ComfySettings(BaseModel):
    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_timeout: int = Field(default=600, ge=30, le=3600)
    comfyui_profiles: dict[Literal["simple", "advanced"], ComfyProfile] = Field(
        default_factory=dict
    )
    comfyui_presets: dict[str, ComfyPreset] = Field(default_factory=dict, max_length=32)
    comfyui_assignments: dict[Literal["simple", "advanced"], str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_presets(self) -> "ComfySettings":
        if any(not key or len(key) > 120 for key in self.comfyui_presets):
            raise ValueError("Preset identifiers must contain 1 to 120 characters.")
        if any(key not in self.comfyui_presets for key in self.comfyui_assignments.values()):
            raise ValueError("A selected ComfyUI preset is missing. Select an available preset.")
        size = sum(len(p.model_dump_json().encode()) for p in self.comfyui_presets.values())
        if size > 2 * 1024 * 1024:
            raise ValueError("The ComfyUI preset library exceeds 2 MiB.")
        return self


def validate_comfy_settings(data: dict) -> None:
    settings = ComfySettings.model_validate(data)
    active = [
        key for key in ("simple", "advanced") if data.get(f"{key}_model_provider") == "comfyui"
    ]
    if not active:
        return
    validate_provider_url(settings.comfyui_url)
    for key in active:
        profile = select_profile({**data, "comfyui_profile": key})
        if not profile or not profile.generate:
            raise ValueError(f"Configure a base ComfyUI workflow for the {key} profile.")
        if (
            isinstance(profile, ComfyPreset)
            and profile.auto_prompt_template
            and not profile.prompt_rules
        ):
            raise ValueError(
                "Automatic model detection is uncertain. Choose a prompt template manually."
            )


def select_profile(options: dict) -> ComfyProfile | ComfyPreset | None:
    settings = ComfySettings.model_validate(options)
    profile_name = options.get("comfyui_profile", "simple")
    selected = settings.comfyui_assignments.get(profile_name)
    if selected:
        preset = settings.comfyui_presets[selected]
        if preset.auto_prompt_template and not preset.prompt_rules:
            raise ValueError(
                "Automatic model detection is uncertain. Choose a prompt template manually."
            )
        return preset
    return settings.comfyui_profiles.get(profile_name)


def select_workflow(options: dict, *, reference: bool = False) -> ComfyWorkflow:
    profile = select_profile(options)
    workflow = getattr(profile, "reference" if reference else "generate", None)
    if not workflow:
        mode = "image" if reference else "base"
        raise ValueError(
            f"No {mode} ComfyUI workflow configured for {options.get('comfyui_profile', 'simple')}."
        )
    return workflow


def prompt_rules(options: dict) -> ImagePromptRules | None:
    return getattr(select_profile(options), "prompt_rules", None)
