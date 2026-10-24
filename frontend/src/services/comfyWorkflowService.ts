import type { ComfyWorkflow } from '@/types/comfyui'

export function parseApiGraph(text: string): ComfyWorkflow['graph'] {
  if (new TextEncoder().encode(text).length > 262144) throw new Error('Maximum workflow size is 256 KiB.')
  const graph = JSON.parse(text) as ComfyWorkflow['graph']
  if (!graph || typeof graph !== 'object' || Array.isArray(graph)) throw new Error('Expected an API workflow object.')
  const nodes = Object.values(graph)
  if (!nodes.length || nodes.length > 256 || nodes.some(node => !node || typeof node.class_type !== 'string' || !node.inputs || typeof node.inputs !== 'object' || Array.isArray(node.inputs))) {
    throw new Error('Export an API workflow from ComfyUI. The editor JSON is not supported.')
  }
  return graph
}

export function replaceGraph(workflow: ComfyWorkflow, graph: ComfyWorkflow['graph']): ComfyWorkflow {
  const bindings = Object.fromEntries(Object.entries(workflow.bindings).filter(([name, binding]) => {
    const value = graph[binding.node_id]?.inputs[binding.input_name]
    return ['prompt', 'negative_prompt', 'image'].includes(name) ? typeof value === 'string' : typeof value === 'number' && Number.isInteger(value)
  }))
  const outputs = Object.entries(graph).filter(([, node]) => node.class_type === 'SaveImage')
  const output = graph[workflow.output_node] ? workflow.output_node : outputs.length === 1 ? outputs[0]![0] : ''
  return { ...workflow, graph, bindings, output_node: output }
}
