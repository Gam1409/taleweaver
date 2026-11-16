import { apiFetch, authHeaders } from '@/services/http'
import { responseError } from '@/services/apiErrors'
import type { ItemDraft } from '@/services/itemGeneration'
import type { PersonalityProfile } from '@/services/npcPersonality'

export interface NpcItemDraft extends ItemDraft { worn: boolean }
export interface NpcDraft {
  name: string
  description: string
  goal: string
  character: string
  gender: string | null
  age_years: number | null
  appearance: { age_years?: number | null; hair: string; eyes: string; build: string; features: string }
  personality_profile: PersonalityProfile
  hp: number
  stamina: number
  mana: number
  moveable: boolean
  is_killable: boolean
  items: NpcItemDraft[]
}
export interface NpcDraftInput {
  brief: string
  scene_id: string
  age_years: number | null
  include_clothing: boolean
  include_underwear: boolean
  include_items: boolean
}

async function post<T>(adventureId: string, endpoint: string, payload: object): Promise<T> {
  const response = await apiFetch(`/adventures/${adventureId}/editor/${endpoint}`, {
    method: 'POST', headers: authHeaders(true), body: JSON.stringify(payload), timeoutMs: null,
  })
  if (!response.ok) {
    throw await responseError(response, endpoint === 'generate-npc-draft' ? 'Could not generate NPC' : 'Could not save NPC')
  }
  return response.json()
}
export function generateNpcDraft(adventureId: string, input: NpcDraftInput): Promise<NpcDraft> {
  return post(adventureId, 'generate-npc-draft', input)
}
export function createNpcWithItems(adventureId: string, sceneId: string, draft: NpcDraft, creationId: string) {
  return post<{ npc_id: string; item_ids: string[] }>(adventureId, 'npc-with-items', {
    scene_id: sceneId, draft, creation_id: creationId,
  })
}
