export type BindingName = 'prompt' | 'negative_prompt' | 'seed' | 'width' | 'height' | 'image'
export interface ComfyNode {
  class_type: string
  inputs: Record<string, unknown>
  _meta?: { title?: string }
}
export interface ComfyWorkflow {
  name: string
  graph: Record<string, ComfyNode>
  bindings: Partial<Record<BindingName, { node_id: string; input_name: string }>>
  output_node: string
}
export interface ComfyProfile {
  generate: ComfyWorkflow | null
  reference: ComfyWorkflow | null
}
export interface ComfyOptions {
  comfyui_url: string
  comfyui_timeout: number
  comfyui_profiles: Partial<Record<'simple' | 'advanced', ComfyProfile>>
  comfyui_profile?: 'simple' | 'advanced'
}
