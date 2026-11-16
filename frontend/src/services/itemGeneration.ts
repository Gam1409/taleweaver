import type { ClothingData } from '@/services/clothingAuthoring'
import { authHeaders, apiFetch } from '@/services/http'
import { responseError } from '@/services/apiErrors'

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
  const response = await apiFetch(`/adventures/${adventureId}/editor/${endpoint}`, { timeoutMs: null,
    method: 'POST', headers: authHeaders(true), body: JSON.stringify(input),
  })
  if (!response.ok) {
    throw await responseError(response, 'Item generation failed')
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
