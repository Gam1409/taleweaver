import type { EntityCreateData, EntityEditData } from '@/services/entityService'

type ResourceValue = number | '' | null | undefined
type ResourceFields = { hp?: ResourceValue; stamina?: ResourceValue; mana?: ResourceValue }
export type EntityAuthoringFields = Omit<Partial<EntityEditData>, keyof ResourceFields> & ResourceFields & {
  entity_id?: string
}

/** Preserve explicit zero while retaining creation defaults for empty inputs. */
export function characterResourceFields(data: ResourceFields, fallback?: number) {
  const value = (input: ResourceValue) => input === '' || input == null ? fallback : Number(input)
  return { hp: value(data.hp), stamina: value(data.stamina), mana: value(data.mana) }
}

interface SwitchSource {
  on_success_script?: string | null
  on_failure_script?: string | null
  metadata_json?: {
    on_success_script?: string | null
    on_failure_script?: string | null
    switch?: { on_success_script?: string | null; on_failure_script?: string | null }
  }
}

/** Read current payloads and legacy flat/nested switch metadata without losing clears. */
export function switchScriptFields(source?: SwitchSource | null) {
  const metadata = source?.metadata_json
  const config = metadata?.switch
  if (config && typeof config === 'object' && !Array.isArray(config)) return {
    on_success_script: config.on_success_script ?? '',
    on_failure_script: config.on_failure_script ?? '',
  }
  return {
    on_success_script: source?.on_success_script ?? metadata?.on_success_script ?? '',
    on_failure_script: source?.on_failure_script ?? metadata?.on_failure_script ?? '',
  }
}

const containerFields = ['code_to_unlock', 'item_to_unlock', 'rule_to_unlock', 'unlock_expression',
  'on_unlock_success_script', 'on_unlock_success_text', 'on_unlock_failure_script', 'on_unlock_failure_text'] as const
const craftFields = ['craft_guard_expression', 'on_craft_success_script', 'on_craft_success_text',
  'on_craft_failure_script', 'on_craft_failure_text'] as const

function itemMetadata(data: EntityAuthoringFields, itemType: string): Record<string, unknown> {
  const metadata: Record<string, unknown> = {}
  if (itemType === 'CONTAINER') {
    metadata.locked = Boolean(data.locked)
    for (const field of containerFields) metadata[field] = data[field] ?? ''
  }
  if (itemType === 'READABLE') {
    metadata.text_log_content = String(data.text_log_content || '').trim()
    metadata.text_log_format = String(data.text_log_format || 'DOCUMENT').toUpperCase()
    metadata.on_read_script = data.on_read_script ?? ''
    metadata.on_read_text = data.on_read_text ?? ''
  }
  if (itemType === 'CONSTRUCTABLE') {
    for (const field of craftFields) metadata[field] = data[field] ?? ''
  }
  if (itemType === 'COMBINABLE') metadata.reveals_item_id = data.reveals_item_id || null
  if (itemType === 'CONSUMABLE') metadata.effects = data.effects || {}
  if (itemType === 'SWITCH') {
    const scripts = switchScriptFields(data)
    Object.assign(metadata, {
      switch_states: data.switch_states || [],
      switch_initial_state: data.switch_initial_state || '',
      switch_transitions: data.switch_transitions || [],
      ...scripts,
      switch: { states: data.switch_states || [], initial_state: data.switch_initial_state || '',
        transitions: data.switch_transitions || [], outcomes: [], ...scripts },
    })
  }
  const mode = data.pickup_trigger_mode || 'silent', cue = data.pickup_trigger_cue || ''
  if (mode !== 'silent' || cue) metadata.pickup_trigger = { mode, cue }
  return metadata
}

/** Project the real modal's normalized output through the established create API. */
export function createEntityPayload(type: 'npc' | 'object', sceneId: string, entityId: string,
  data: EntityAuthoringFields): EntityCreateData {
  const base = { entity_id: entityId, scene_id: sceneId, name: String(data.name || '').trim(),
    description: String(data.description || '').trim() }
  if (type === 'npc') return {
    ...base, entity_type: 'NPC', ...characterResourceFields(data, 20),
    goal: String(data.goal || '').trim() || undefined,
    character: String(data.character || '').trim() || undefined,
    gender: data.gender, age_years: data.age_years, personality_profile: data.personality_profile || {},
    is_killable: Boolean(data.is_killable), moveable: Boolean(data.moveable),
    allowed_scenes: data.allowed_scenes || [], notes: String(data.notes || '').trim() || undefined,
    is_hidden: Boolean(data.is_hidden), reveal_rule: String(data.reveal_rule || '').trim() || undefined,
    spatial_position: String(data.spatial_position || '').trim() || undefined, inventory: data.inventory || [],
    on_defeat_script: data.on_defeat_script || undefined, on_defeat_text: data.on_defeat_text || undefined,
    on_protagonist_enters_scene_script: data.on_protagonist_enters_scene_script || undefined,
    on_protagonist_enters_scene_text: data.on_protagonist_enters_scene_text || undefined,
  }
  const itemType = String(data.item_type || 'DEFAULT').toUpperCase()
  return {
    ...base, entity_type: 'OBJECT', item_type: itemType,
    is_portable: data.is_portable ?? itemType !== 'SWITCH', inventory: data.inventory || [],
    wearable_slots: data.wearable_slots || undefined, clothing: itemType === 'WEARABLE' ? data.clothing : undefined,
    combination_ingredients: data.combination_ingredients || undefined,
    stat_modifier_strength: data.stat_modifier_strength || undefined, is_hidden: data.is_hidden ?? undefined,
    reveal_rule: data.reveal_rule || undefined, spatial_position: data.spatial_position || undefined,
    on_pickup_script: data.on_pickup_script || undefined, on_pickup_text: data.on_pickup_text || undefined,
    on_drop_script: data.on_drop_script || undefined, on_drop_text: data.on_drop_text || undefined,
    on_equip_script: data.on_equip_script || undefined, on_equip_text: data.on_equip_text || undefined,
    on_unequip_script: data.on_unequip_script || undefined, on_unequip_text: data.on_unequip_text || undefined,
    metadata_json: itemMetadata(data, itemType),
  }
}
