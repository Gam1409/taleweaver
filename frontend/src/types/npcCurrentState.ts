/** Read-only, server-filtered current observations; hidden inventory is never included. */
import type { ItemStateValue } from '@/utils/equipmentSlots'

export interface NpcVisibleGarment {
  item_id: string
  name: string
  description: string
  image_url: string | null
  layer: number
  visible_regions: string[]
  uncovered_regions: string[]
  slots?: string[]
  current_state?: ItemStateValue[]
}

export interface NpcKnownCondition {
  id: string
  target_id: string
  target_name?: string | null
  kind: 'injury' | 'contamination' | 'fluid' | 'pain' | 'other' | 'item_state'
  part: string
  detail: string
  status: 'active' | 'treated' | 'reduced'
  observation: 'visible' | 'recorded'
  last_changed_minute: number | null
  display_slots?: string[]
  visibility?: 'public' | 'private'
  current_detail?: string
  updated_revision?: number
  observed_message_id?: string | null
}

export interface NpcCurrentState {
  layout?: {
    form: 'humanoid' | 'non_humanoid' | 'unknown'
    silhouette: 'male' | 'female' | 'neutral'
  }
  availability: 'present' | 'not_present'
  game_minute: number
  clothing: {
    status: 'available' | 'unavailable'
    detail_limited: boolean
    items: NpcVisibleGarment[]
    placement_status?: 'available' | 'unassessed' | 'unavailable'
    placement_slots?: { key: string; status: 'empty' | 'occupied' | 'unconfirmed' }[]
  }
  conditions: {
    status: 'available' | 'unavailable'
    items: NpcKnownCondition[]
  }
}
