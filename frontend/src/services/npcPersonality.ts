import { authHeaders, apiFetch } from '@/services/http'

export type PersonalityProfile = Record<string, string>
export interface PersonalityField {
  key: string
  label: string
  options: { value: string; label: string; help: string }[]
}

async function read<T>(url: string, body?: object): Promise<T> {
  const response = await apiFetch(`/adventures/${url}`, { timeoutMs: body ? null : 15_000,
    method: body ? 'POST' : 'GET', headers: authHeaders(Boolean(body)),
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not load personality settings.')
  }
  return response.json()
}

export const loadPersonalityCatalog = () => read<PersonalityField[]>('editor/personality-options')
export const suggestPersonality = (adventureId: string, source: {name: string; description: string; goal: string; character: string}) =>
  read<PersonalityProfile>(`${adventureId}/editor/suggest-personality`, source)
