import { authHeaders, apiFetch } from '@/services/http'

export interface ClothingData {
  category?: 'clothing' | 'armor' | 'accessory'
  layer: number
  coverage: string[]
  opaque?: boolean
  underwear?: boolean
  description?: string
}
export type ClothingDraft = Partial<ClothingData>

export async function prepareClothing(adventureId: string, input: {
  name: string; description: string; wearable_slots: string[]; clothing: ClothingDraft
}): Promise<ClothingData> {
  const response = await apiFetch(`/adventures/${adventureId}/editor/prepare-clothing`, { timeoutMs: null,
    method: 'POST', headers: authHeaders(true), body: JSON.stringify(input),
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not prepare clothing data. Check the existing values and try again.')
  }
  return response.json()
}
