/** Read-only, server-filtered current observations; hidden inventory is never included. */
export interface NpcVisibleGarment {
  item_id: string
  name: string
  description: string
  image_url: string | null
  layer: number
  visible_regions: string[]
  uncovered_regions: string[]
  slots?: string[]
}

export interface NpcKnownCondition {
  id: string
  target_id: string
  target_name?: string | null
  kind: 'injury' | 'contamination' | 'fluid' | 'pain' | 'other'
  part: string
  detail: string
  status: 'active' | 'treated' | 'reduced'
  observation: 'visible' | 'recorded'
  last_changed_minute: number | null
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
  }
  conditions: {
    status: 'available' | 'unavailable'
    items: NpcKnownCondition[]
  }
}
