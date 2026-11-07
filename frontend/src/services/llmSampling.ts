/** Empty profiles preserve server defaults; each role can opt into an independent profile. */
import type { LLMRole } from './llmRoleEndpoints'

export interface SamplingProfile {
  temperature: number | null
  top_p: number | null
  top_k: number | null
  min_p: number | null
  repetition_penalty: number | null
  local_extensions: boolean
}

export interface SamplingSettings {
  defaults: SamplingProfile
  roles: Partial<Record<LLMRole, { enabled: boolean; profile: SamplingProfile }>>
}

export const SAMPLING_FIELDS = [
  {
    key: 'temperature',
    label: 'Temperature',
    min: 0,
    max: 2,
    step: 0.05,
    local: false,
    help: 'Controls how strongly the model favors likely next tokens. Lower values usually make technical answers more consistent; higher values allow more varied prose and can increase mistakes. Zero still does not guarantee identical answers. There is no universal best value.'
  },
  {
    key: 'top_p',
    label: 'Top P',
    min: 0.01,
    max: 1,
    step: 0.01,
    local: false,
    help: 'Keeps the smallest set of candidate tokens whose combined probability reaches this value. Lower values narrow the choices; 1 disables this filter. Temperature and other filters interact, so change one setting at a time.'
  },
  {
    key: 'top_k',
    label: 'Top K',
    min: 0,
    max: 1000,
    step: 1,
    local: true,
    help: 'Keeps only the K most likely next tokens. Small values narrow vocabulary and variation. Zero disables this filter on supported local servers. This is a local-server extension, not a standard OpenAI parameter.'
  },
  {
    key: 'min_p',
    label: 'Min P',
    min: 0,
    max: 1,
    step: 0.01,
    local: true,
    help: 'Removes tokens whose probability is below this fraction of the most likely token. Larger values filter more aggressively; zero disables it. Combining strong Min P, Top P and Top K filters can make prose repetitive.'
  },
  {
    key: 'repetition_penalty',
    label: 'Repetition penalty',
    min: 0.01,
    max: 2,
    step: 0.01,
    local: true,
    help: 'Changes the weight of tokens already used. One is neutral; values above one discourage repetition. Strong penalties can damage names, grammar and JSON. This differs from OpenAI frequency and presence penalties.'
  }
] as const

export function emptyProfile(): SamplingProfile {
  return {
    temperature: null,
    top_p: null,
    top_k: null,
    min_p: null,
    repetition_penalty: null,
    local_extensions: false
  }
}

export function normalizeSampling(value?: Partial<SamplingSettings> | null): SamplingSettings {
  return {
    defaults: { ...emptyProfile(), ...value?.defaults },
    roles: Object.fromEntries(
      Object.entries(value?.roles ?? {}).map(([role, item]) => [
        role,
        {
          enabled: item.enabled,
          profile: { ...emptyProfile(), ...item.profile }
        }
      ])
    )
  }
}

export function effectiveSampling(value: SamplingSettings, role: LLMRole): SamplingProfile {
  const override = value.roles[role]
  return { ...(override?.enabled ? override.profile : value.defaults) }
}

export function toggleRoleSampling(
  value: SamplingSettings,
  role: LLMRole,
  enabled: boolean
): SamplingSettings {
  const next = normalizeSampling(value)
  next.roles[role] = { enabled, profile: next.roles[role]?.profile ?? { ...next.defaults } }
  return next
}
