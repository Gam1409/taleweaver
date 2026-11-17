const NATIVE_PROFILE_HELP = 'Uses the existing provider adapter checks. Native tools require a compatible model and provider; the profile does not guarantee native support.'

export const NPC_TOOL_PROFILES = [
  { id: 'auto', label: 'Auto', help: 'Preserves the existing configured tool-calling behavior.' },
  { id: 'anthropic', label: 'Anthropic', help: NATIVE_PROFILE_HELP },
  { id: 'openai', label: 'OpenAI', help: NATIVE_PROFILE_HELP },
  { id: 'mistral', label: 'Mistral', help: NATIVE_PROFILE_HELP },
  { id: 'gemma', label: 'Gemma', help: 'With Automatic protocol, prefers JSON compatibility for current native template limits. Explicit Native requires support for the supplied tool schemas.' },
  { id: 'deepseek', label: 'DeepSeek', help: NATIVE_PROFILE_HELP },
  { id: 'qwen', label: 'Qwen', help: 'With Automatic protocol, prefers JSON compatibility because native argument typing varies by runtime and parser. Explicit Native requires support for the supplied tool schemas.' },
] as const

export type NpcToolProfile = typeof NPC_TOOL_PROFILES[number]['id']

export const NPC_TOOL_PROFILE_REQUIREMENTS = 'Requires a compatible model and server. Native tools also require a compatible tool-aware chat template. Support varies by model version. The native/JSON protocol and request limits stay as selected.'
export const NPC_TOOL_PROTOCOL_HELP = 'Automatic considers the selected profile and provider support; Gemma and Qwen profiles prefer JSON compatibility. Choose JSON compatibility for a server without native tools.'

export function findNpcToolProfile(id: string = 'auto') {
  return NPC_TOOL_PROFILES.find(profile => profile.id === id)
}
