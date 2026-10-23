"""Typed, bounded API-workflow settings for the ComfyUI image provider."""

import copy
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class ComfySettings(BaseModel):
    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_timeout: int = Field(default=600, ge=30, le=3600)
    comfyui_profiles: dict[Literal["simple", "advanced"], ComfyProfile] = Field(
        default_factory=dict
    )


def validate_comfy_settings(data: dict) -> None:
    settings = ComfySettings.model_validate(data)
    active = [
        key for key in ("simple", "advanced") if data.get(f"{key}_model_provider") == "comfyui"
    ]
    if not active:
        return
    validate_provider_url(settings.comfyui_url)
    for key in active:
        profile = settings.comfyui_profiles.get(key)
        if not profile or not profile.generate:
            raise ValueError(f"Configure a base ComfyUI workflow for the {key} profile.")


def select_workflow(options: dict, *, reference: bool = False) -> ComfyWorkflow:
    settings = ComfySettings.model_validate(options)
    profile_name = options.get("comfyui_profile", "simple")
    profile = settings.comfyui_profiles.get(profile_name)
    workflow = getattr(profile, "reference" if reference else "generate", None)
    if not workflow:
        mode = "image" if reference else "base"
        raise ValueError(f"No {mode} ComfyUI workflow configured for {profile_name}.")
    return workflow
