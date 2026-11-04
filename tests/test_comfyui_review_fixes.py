"""Custom node schemas preserve socket/widget alignment and model pickers."""

import pytest

from backend.core.comfyui_starters import model_choices, starter_workflow
from backend.engine.comfyui_validation import node_input_schema


@pytest.mark.parametrize("kind", ["STRING", "INT", "FLOAT", "BOOLEAN", ["choice"]])
def test_force_input_is_a_socket(kind):
    schema = node_input_schema(
        {
            "input": {
                "required": {
                    "linked": [kind, {"forceInput": True}],
                    "text": ["STRING", {"forceInput": False}],
                    "strength": ["FLOAT", {"default": 1}],
                }
            }
        }
    )
    assert schema == [
        {"name": "linked", "kind": "socket"},
        {"name": "text", "kind": "string"},
        {"name": "strength", "kind": "float"},
    ]


def test_quadruple_encoder_and_upscale_model_choices():
    workflow = starter_workflow("sdxl")
    workflow.graph.update(
        {
            "quad": {
                "class_type": "QuadrupleCLIPLoader",
                "inputs": {"clip_name4": "fourth.safetensors"},
            },
            "upscale": {
                "class_type": "UpscaleModelLoader",
                "inputs": {"model_name": "upscale.pth"},
            },
        }
    )
    registry = {
        "QuadrupleCLIPLoader": {"input": {"required": {"clip_name4": [["fourth.safetensors"]]}}},
        "UpscaleModelLoader": {"input": {"required": {"model_name": [["upscale.pth"]]}}},
    }
    choices = {item["input_name"]: item["choices"] for item in model_choices(workflow, registry)}
    assert choices["clip_name4"] == ["fourth.safetensors"]
    assert choices["model_name"] == ["upscale.pth"]
