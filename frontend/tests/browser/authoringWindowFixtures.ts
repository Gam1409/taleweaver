export const scenes = [{ id: 'ARCHIVE', name: 'The Old Archive' }, { id: 'HARBOUR', name: 'Harbour' }]
export const objects = [{ id: 'LETTER', name: 'Sealed letter', description: 'A letter bearing the lighthouse seal.', item_type: 'READABLE', current_scene_id: 'ARCHIVE' }]
export const npc = { id: 'MIRA', name: 'Mira', description: 'A patient archivist.', character: 'Curious and methodical.', goal: 'Find the missing coastal chart.', metadata_json: { special_actions: [] } }
export const references = [...scenes.map(scene => ({ ...scene, type: 'SCENE' })), ...objects.map(item => ({ ...item, type: 'OBJECT' })), { ...npc, type: 'NPC' }]
export const adventure = {
  id: 'coast', title: 'Letters from the Coast', rule_enforcement_mode: 'rpg', scenes, objects, npcs: [npc],
  sequences: [{ id: 'CHAPTER_ONE', order: 1, title: 'The old chart', description: 'Find the missing chart.', walkthrough: '', end_condition: 'The chart is found.', exp_reward: 50 }],
  quests: [{ id: 'FIND_LETTER', title: 'The lighthouse letter', description: 'Find the lighthouse letter.', goal: 'Read the letter.', impact: 'A new coastal route.', is_main: false, status: 'open', exp_reward: 50 }],
  awards: [{ key: 'COASTAL_READER', title: 'Coastal reader', description: 'Read the lighthouse letter.', tier: 'bronze', exp_reward: 10 }],
  scripts: [{ id: 'ARCHIVE_LIGHT', name: 'Archive light', trigger: 'on_enter_scene', target_id: 'ARCHIVE', code: 'tw.narrate("The archive is quiet.")', is_active: true, priority: 10 }],
}
export const entityForm = {
  name: npc.name, teaser: '', description: npc.description, hp: 100, stamina: 50, mana: 50, goal: npc.goal, character: npc.character,
  gender: null, age_years: 32, personality_profile: {}, outfit_completion: null, is_killable: true, item_type: 'READABLE', is_portable: true,
  locked: false, code_to_unlock: '', item_to_unlock: '', inventory_input: [], text_log_content: 'Coastal records.', text_log_format: 'plain', entity_id: 'MIRA',
  wearable_slots_input: [], clothing: null, combination_ingredients_input: [], reveal_rule: '', is_hidden: false, spatial_position: '', reveals_item_id: '',
  switch_states_json: '["OFF","ON"]', switch_initial_state: 'OFF', switch_transitions_json: '[]', effects_hp: 0, effects_stamina: 0, effects_mana: 0, stat_modifier_strength: 0,
  moveable: true, allowed_scenes_input: [], notes: '',
}
export const proposals = [{ title: 'Connect the coastal path', summary: 'Use the known harbour route.', rationale: 'Keep both existing locations.', patches: [{ target_type: 'exit', target_id: 'COASTAL_PATH', field_updates: { to_scene_id: 'HARBOUR' } }] }]
export const finding = { code: 'MISSING_EXIT_TARGET', message: 'The coastal path needs a destination.', severity: 'error', location: 'exits.COASTAL_PATH', context: { exit_id: 'COASTAL_PATH' } }

/** All API operations stay in memory; this fixture never calls a model or backend. */
export function installAuthoringWindowApi() {
  const requests: string[] = [], unhandled: string[] = [], events: string[] = []
  const originalFetch = window.fetch.bind(window)
  window.fetch = async (input, options) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const url = new URL(raw, window.location.origin)
    if (!url.pathname.startsWith('/api/')) return originalFetch(input, options)
    const path = url.pathname.slice(4)
    requests.push(`${options?.method || 'GET'} ${path}`)
    if (path.endsWith('/editor/personality-options')) return Response.json(['openness', 'conscientiousness', 'sociability', 'empathy', 'confidence', 'patience'].map(key => ({ key, label: key[0].toUpperCase() + key.slice(1), options: [{ value: 'balanced', label: 'Balanced', help: 'Responds to the current situation.' }, { value: 'high', label: 'High', help: 'A strong tendency.' }] })))
    if (path.endsWith('/living-world/capabilities')) return Response.json({ concordia_available: true, inference_serialization_enabled: true })
    if (path.endsWith('/visual-presets')) return Response.json({ source: 'current', selection: {}, presets: [], effective: { provider: 'Fictional provider', models: [] } })
    if (path.endsWith('/editor/validation/latest')) return Response.json({ structural_findings: [finding], ai_findings: [], ai_skipped_reason: 'ai_not_requested', run_at: '2026-01-01T12:00:00Z' })
    if (path.includes('/special-attacks')) return Response.json([])
    if (path.includes('/settings')) return Response.json({})
    unhandled.push(`${options?.method || 'GET'} ${path}`)
    return Response.json({ detail: 'This fixture does not run backend operations.' }, { status: 501 })
  }
  return { requests, unhandled, events }
}
