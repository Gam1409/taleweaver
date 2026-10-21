/** Independent connection settings for all five LLM roles. */
export type OllamaRole = 'small' | 'complex' | 'generator' | 'compression' | 'play_agent'

export interface OllamaTestOptions {
  role: OllamaRole
  apiMode?: 'generate' | 'chat'
  url: string
  timeout: number | null
  numCtx: number | null
}

export const normalizeOllamaNumber = (value: unknown): number | null => {
  if (value == null || (typeof value === 'string' && !value.trim())) return null
  return Number(value)
}

export const normalizeOllamaRoleNumbers = <T extends Record<string, unknown>>(form: T): T => {
  const result = { ...form }
  const values: Record<string, unknown> = result
  for (const role of ['small', 'complex', 'generator', 'compression', 'play_agent']) {
    for (const option of ['timeout', 'num_ctx']) {
      const key = `${role}_ollama_${option}`
      values[key] = normalizeOllamaNumber(form[key])
    }
  }
  return result
}
