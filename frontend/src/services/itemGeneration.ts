import type { ClothingData } from '@/services/clothingAuthoring'
import { API_BASE, authHeaders } from '@/services/http'

export interface ItemDraft {
  name: string
  description: string
  item_type: string
  is_portable: boolean
  wearable_slots: string[]
  text_log_content: string
  clothing: ClothingData | null
}

async function generate<T>(adventureId: string, endpoint: string, input: object): Promise<T> {
  const response = await fetch(`${API_BASE}/adventures/${adventureId}/editor/${endpoint}`, {
    method: 'POST', headers: authHeaders(true), body: JSON.stringify(input),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Item generation failed. Please try again.')
  }
  return response.json()
}

export function generateItemDraft(adventureId: string, brief: string, itemType: string, slots: string[]) {
  return generate<ItemDraft>(adventureId, 'generate-item-draft', {
    brief, item_type: itemType, wearable_slots: slots,
  })
}

export function generateItemDescription(adventureId: string, name: string, description: string, itemType: string) {
  return generate<{ description: string }>(adventureId, 'generate-item-description', {
    name, description, item_type: itemType,
  })
}
