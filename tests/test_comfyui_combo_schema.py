"""Live ComfyUI 0.35 combo metadata stays selectable and survives widget import."""

from copy import deepcopy

import pytest

from backend.core.comfyui_schema import combo_choices
from backend.core.comfyui_starters import model_choices, starter_workflow
from backend.engine.comfyui_validation import inspect_workflow, node_input_schema


@pytest.mark.parametrize(
    "spec",
    [
        [["Anime6B.safetensors"]],
        ["COMBO", {"options": ["Anime6B.safetensors"], "multiselect": False}],
    ],
)
def test_old_and_current_combos_offer_the_same_model_and_widget_layout(spec):
    workflow = starter_workflow("sd15")
    workflow.graph["upscale"] = {
        "class_type": "UpscaleModelLoader",
        "inputs": {"model_name": "Anime6B.safetensors"},
    }
    registry = {"UpscaleModelLoader": {"input": {"required": {"model_name": spec}}}}
    options = [row for row in model_choices(workflow, registry) if row["node_id"] == "upscale"]
    assert options == [
        {"node_id": "upscale", "input_name": "model_name", "choices": ["Anime6B.safetensors"]}
    ]
    assert node_input_schema(registry["UpscaleModelLoader"]) == [
        {"name": "model_name", "kind": "combo"}
    ]


def test_current_combo_rejects_unavailable_files_and_preserves_unknown_choices():
    workflow = starter_workflow("sd15")
    registry = {
        node["class_type"]: {
            "input": {"required": {key: ["ANY"] for key in node["inputs"]}},
            "output_node": node["class_type"] == "SaveImage",
        }
        for node in workflow.graph.values()
    }
    registry["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"] = [
        "COMBO",
        {"options": ["installed.safetensors"]},
    ]
    result = inspect_workflow(workflow, registry)
    assert "model.ckpt_name: selected value is not available on the server." in result["errors"]
    empty = deepcopy(registry)
    empty["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][1]["options"] = []
    assert inspect_workflow(workflow, empty)["compatible"] is False
    unknown = deepcopy(registry)
    unknown["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"] = [
        "COMBO",
        {"remote": True},
    ]
    assert inspect_workflow(workflow, unknown)["compatible"] is True


def test_forced_combo_is_a_socket_and_does_not_consume_editor_widget_values():
    info = {
        "input": {
            "required": {
                "connected_model": ["COMBO", {"options": ["a"], "forceInput": True}],
                "model": ["COMBO", {"options": ["a"]}],
                "steps": ["INT", {"default": 20}],
            }
        }
    }
    assert node_input_schema(info) == [
        {"name": "connected_model", "kind": "socket"},
        {"name": "model", "kind": "combo"},
        {"name": "steps", "kind": "int"},
    ]


@pytest.mark.parametrize(
    "spec,expected",
    [
        (None, None),
        ([], None),
        (["STRING", {"multiline": True}], None),
        (["COMBO", {"options": []}], []),
        (["COMBO", {"options": "remote"}], None),
        (["COMBO", {"options": [1, 2]}], [1, 2]),
    ],
)
def test_missing_and_empty_options_remain_distinct(spec, expected):
    assert combo_choices(spec) == expected
