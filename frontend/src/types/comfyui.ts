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
  dimension_multiple?: 8 | 16 | 32 | 64
}
export interface ComfyProfile {
  generate: ComfyWorkflow | null
  reference: ComfyWorkflow | null
}
export interface ImagePromptRules {
  template_id: string
  format: 'description' | 'tags' | 'hybrid'
  language: string
  max_words: number
  adapt_with_llm: boolean
  prefix: string
  suffix: string
  negative_prompt: string
  instructions: string
}
export interface PromptTemplate {
  id: string
  name: string
  source: string
  notes: string
  rules: ImagePromptRules
}
export interface ComfyPreset extends ComfyProfile {
  name: string
  prompt_rules: ImagePromptRules | null
  auto_prompt_template: boolean
  mature_themes?: boolean
}
export interface ComfyOptions {
  comfyui_url: string
  comfyui_timeout: number
  comfyui_profiles: Partial<Record<'simple' | 'advanced', ComfyProfile>>
  comfyui_profile?: 'simple' | 'advanced'
  comfyui_presets?: Record<string, ComfyPreset>
  comfyui_assignments?: Partial<Record<'simple' | 'advanced', string>>
}
