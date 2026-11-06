/** One shared API endpoint with optional overrides for the five text roles. */
export const LLM_ROLES = ['small', 'complex', 'generator', 'compression', 'play_agent'] as const
export type LLMRole = typeof LLM_ROLES[number]

export function customOpenAIUrl(form: Record<string, unknown>, role?: LLMRole): string {
  const override = role ? String(form[`${role}_custom_openai_url`] || '').trim() : ''
  return (override || String(form.custom_openai_url || '').trim()).replace(/\/+$/, '')
}

export function useSharedApiUrlForAll(form: Record<string, unknown>): void {
  for (const role of LLM_ROLES) form[`${role}_custom_openai_url`] = ''
}
