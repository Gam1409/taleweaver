export interface EquipmentDisplayItem {
  id: string
  name: string
  image_url?: string | null
  description?: string
  layer?: number
  uncovered_regions?: string[]
  [key: string]: unknown
}

export type EquipmentDisplay = Record<string, EquipmentDisplayItem[]>

export const EQUIPMENT_SLOTS = [
  { key: 'Head', label: 'Head', icon: 'ra-helmet', top: '10%', left: '50%' },
  { key: 'Neck', label: 'Neck', icon: 'ra-gem-pendant', top: '18%', left: '76%' },
  { key: 'Chest', label: 'Chest', icon: 'ra-vest', top: '30%', left: '50%' },
  { key: 'Arms', label: 'Arms', icon: 'ra-hand', top: '26%', left: '20%' },
  { key: 'Hands', label: 'Hands', icon: 'ra-hand', top: '46%', left: '16%' },
  { key: 'MainHand', label: 'Main hand', icon: 'ra-sword', top: '68%', left: '16%' },
  { key: 'Ring_1', label: 'Ring 1', icon: 'ra-fire-ring', top: '38%', left: '82%' },
  { key: 'Ring_2', label: 'Ring 2', icon: 'ra-fire-ring', top: '54%', left: '82%' },
  { key: 'OffHand', label: 'Off hand', icon: 'ra-shield', top: '72%', left: '82%' },
  { key: 'Legs', label: 'Legs', icon: 'ra-boot-stomp', top: '64%', left: '50%' },
  { key: 'Feet', label: 'Feet', icon: 'ra-shoe-prints', top: '86%', left: '50%' }
] as const

export const BODY_ITEM_SLOTS = [
  { key: 'BodyVaginal', label: '', icon: 'ra-emerald', top: '57%', left: '50%' },
  { key: 'BodyAnal', label: '', icon: 'ra-emerald', top: '64%', left: '50%' }
] as const

export function legacyEquipment(equipment: Record<string, unknown>): EquipmentDisplay {
  const result: EquipmentDisplay = {}
  for (const slot of EQUIPMENT_SLOTS) {
    const item = equipment[slot.key]
    if (item && typeof item === 'object' && 'name' in item) {
      result[slot.key] = [
        { ...item, id: String('id' in item ? item.id : slot.key), name: String(item.name) }
      ]
    }
  }
  return result
}
