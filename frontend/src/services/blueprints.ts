import { apiFetch } from '@/services/http'

export interface BlueprintIssue { line: number; message: string; severity: 'error' | 'warning' }
export interface BlueprintCheckResult {
  has_tags: boolean
  errors: BlueprintIssue[]
  warnings: BlueprintIssue[]
  counts: Record<string, number>
}

const OPTION_KEYS = [
  'rule_enforcement_mode', 'scripts_generation_enabled', 'container_generation_enabled',
  'text_log_generation_enabled', 'quest_generation_enabled', 'award_generation_enabled',
  'max_scenes', 'max_items', 'max_sequences',
] as const

export function blueprintOptions(form: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(OPTION_KEYS.filter(key => form[key] !== undefined).map(key => [key, form[key]]))
}

export async function checkBlueprint(text: string, form: Record<string, unknown>, signal?: AbortSignal): Promise<BlueprintCheckResult> {
  const response = await apiFetch('/adventures/blueprint/validate', {
    method: 'POST', includeJson: true, signal,
    body: JSON.stringify({ text, options: blueprintOptions(form) }),
  })
  if (!response.ok) throw new Error('Could not check the blueprint. Keep it within 20,000 characters and try again.')
  return response.json()
}
