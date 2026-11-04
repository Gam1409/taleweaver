"""Compare workflow nodes and literal inputs with ComfyUI's live node registry."""

from typing import Any

from backend.core.comfyui_config import ComfyWorkflow


def _input_errors(node_id: str, inputs: dict, schema: dict) -> list[str]:
    errors = []
    for name, definition in schema.items():
        if name not in inputs or not isinstance(definition, (list, tuple)) or not definition:
            continue
        value = inputs[name]
        choices = definition[0]
        if isinstance(choices, list) and not isinstance(value, list) and value not in choices:
            errors.append(f"{node_id}.{name}: selected value is not available on the server.")
    return errors


def _input_kind(spec: Any) -> str:
    """Classify one INPUT_TYPES entry the way the ComfyUI editor renders it."""
    if isinstance(spec, (list, tuple)) and spec:
        if len(spec) > 1 and isinstance(spec[1], dict) and spec[1].get("forceInput") is True:
            return "socket"
        first = spec[0]
        if isinstance(first, (list, tuple)):
            return "combo"
        if first in {"STRING", "INT", "FLOAT", "BOOLEAN"}:
            return str(first).lower()
    return "socket"


def node_input_schema(info: Any) -> list[dict[str, str]]:
    """Ordered inputs of one ``/object_info`` entry, marked widget vs socket.

    The editor renders combo/STRING/INT/FLOAT/BOOLEAN entries as widgets and
    everything else (MODEL, CLIP, VAE, custom types) as connectable sockets,
    following INPUT_TYPES order (``input_order`` when the server provides it).
    Hidden and deprecated entries live in their own sections and never render,
    so they are not listed either. Works for core and custom node packs alike.
    """
    if not isinstance(info, dict):
        return []
    sections = info.get("input")
    if not isinstance(sections, dict):
        return []
    order = info.get("input_order")
    schema: list[dict[str, str]] = []
    for section in ("required", "optional"):
        definitions = sections.get(section)
        if not isinstance(definitions, dict):
            continue
        names = order.get(section) if isinstance(order, dict) else None
        if not isinstance(names, list) or not names:
            names = list(definitions)
        for name in names:
            if name in definitions:
                schema.append({"name": name, "kind": _input_kind(definitions[name])})
    return schema


def inspect_workflow(workflow: ComfyWorkflow, registry: dict[str, Any]) -> dict:
    required = {node["class_type"] for node in workflow.graph.values()}
    missing = sorted(required - registry.keys())
    errors = [f"Missing node type: {name}" for name in missing]
    for node_id, node in workflow.graph.items():
        info = registry.get(node["class_type"], {})
        inputs = info.get("input", {})
        schema = {**inputs.get("required", {}), **inputs.get("optional", {})}
        mapped = {b.input_name for b in workflow.bindings.values() if b.node_id == node_id}
        literal_inputs = {key: value for key, value in node["inputs"].items() if key not in mapped}
        errors.extend(_input_errors(node_id, literal_inputs, schema))
        errors.extend(
            f"{node_id}.{key}: required input is missing."
            for key in inputs.get("required", {})
            if key not in node["inputs"]
        )
    for binding in workflow.bindings.values():
        info = registry.get(workflow.graph[binding.node_id]["class_type"], {})
        schema = info.get("input", {})
        known = {**schema.get("required", {}), **schema.get("optional", {})}
        if info and binding.input_name not in known:
            errors.append(f"{binding.node_id}.{binding.input_name}: binding is not a server input.")
    output_type = workflow.graph[workflow.output_node]["class_type"]
    if output_type in registry and not registry[output_type].get("output_node"):
        errors.append("Selected output node is not an executable output node.")
    return {
        "compatible": not errors,
        "node_types": len(required),
        "missing_node_types": missing,
        "errors": errors,
        "message": "Static checks only; run a test image to verify execution and image output.",
    }
