import { apiFetch, authHeaders } from '@/services/http'
import type { ClothingData } from '@/services/clothingAuthoring'

export interface OutfitItem {
  item_id?: string | null
  name: string
  description: string
  wearable_slots: string[]
  clothing: ClothingData
}
export interface CharacterOutfitDraft {
  appearance: { age_years?: number | null; hair?: string; eyes?: string; build?: string; features?: string } | null
  outfit: OutfitItem[]
}
export interface OutfitContext {
  allow_underwear: boolean
  owned: { id: string; name: string; description: string; worn: boolean; pending?: boolean; clothing: ClothingData | null; wearable_slots: string[] }[]
}
export interface OutfitTarget { adventureId: string; targetType: string; targetId: string }

async function read<T>(url: string, body?: object): Promise<T> {
  const response = await apiFetch(url, body ? {
    method: 'POST', headers: authHeaders(true), body: JSON.stringify(body), timeoutMs: null,
  } : {})
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not prepare clothing. Check the character and try again.')
  }
  return response.json()
}
export function loadCharacterOutfit(target: OutfitTarget): Promise<OutfitContext> {
  const query = new URLSearchParams({ target_type: target.targetType, target_id: target.targetId })
  return read(`/adventures/${target.adventureId}/editor/character-outfit?${query}`)
}
export function generateCharacterOutfit(target: OutfitTarget, input: {
  brief: string; include_underwear: boolean; name: string; description: string; character: string; goal: string; inventory_ids: string[]
}): Promise<{ draft: CharacterOutfitDraft; context: OutfitContext; notes: string[] }> {
  return read(`/adventures/${target.adventureId}/editor/generate-character-outfit`, {
    target_type: target.targetType, target_id: target.targetId, ...input,
  })
}
