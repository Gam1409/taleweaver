const artwork = `${import.meta.env.BASE_URL}assets/background/background5.jpg`

function world() {
  const protagonist = { id: 'ALEX', entity_type: 'PROTAGONIST', name: 'Alex', description: 'A researcher following the coastal archives.', hp: 100, max_hp: 100, stamina: 50, mana: 50, strength: 10, dexterity: 12, intelligence: 15, wisdom: 14, charisma: 12, armor_class: 10, exp: 120, inventory: ['LETTER'], equipment: {}, stats: {}, scene_id: 'ARCHIVE' }
  const npcs = [
    { id: 'MIRA', name: 'Mira', description: 'The patient keeper of the old archive.', character: 'Curious, methodical and quietly welcoming.', goal: 'Find the missing lighthouse records.' },
    { id: 'OWEN', name: 'Owen', description: 'A harbour keeper who knows the coastal paths.', character: 'Practical and observant.', goal: 'Keep the harbour lights in working order.' },
  ].map(npc => ({ ...npc, entity_type: 'NPC', scene_id: 'ARCHIVE', current_scene_id: 'ARCHIVE', hp: 100, inventory: [], equipment: {}, stats: {} }))
  const objects = [
    { id: 'LETTER', name: 'Sealed letter', entity_type: 'OBJECT', item_type: 'READABLE', description: 'A letter stamped with the lighthouse seal.', is_portable: true, scene_id: 'ARCHIVE', current_scene_id: 'ARCHIVE', stats: {}, metadata_json: { text_log_content: 'Meet me by the lighthouse after the archive closes.', text_log_format: 'LETTER' } },
    { id: 'LAMP', name: 'Reading lamp', entity_type: 'OBJECT', item_type: 'SWITCH', description: 'A brass lamp above the coastal charts.', is_portable: false, scene_id: 'ARCHIVE', current_scene_id: 'ARCHIVE', stats: {}, metadata_json: { switch_states: ['OFF', 'ON'], switch_initial_state: 'OFF', switch_transitions: [] } },
  ]
  const scenes = [
    { id: 'ARCHIVE', name: 'The Old Archive', description: 'Shelves of coastal maps and a letter waiting on the table.' },
    { id: 'HARBOUR', name: 'Harbour', description: 'A quiet harbour at the end of the archive path.' },
    { id: 'LIGHTHOUSE', name: 'Lighthouse', description: 'An old light overlooking the coast.' },
  ].map(scene => ({ ...scene, image_url: artwork, visited: false }))
  const exits = [
    { id: 'ARCHIVE_PATH', from_scene_id: 'ARCHIVE', to_scene_id: 'HARBOUR', label: 'Coastal path', exit_type: 'bidirectional', is_locked: false },
    { id: 'TOWER_STAIR', from_scene_id: 'HARBOUR', to_scene_id: 'LIGHTHOUSE', label: 'Tower stair', exit_type: 'one_way', is_locked: true },
  ]
  return { protagonist, npcs, objects, scenes, exits, entities_all: [protagonist, ...npcs, ...objects] }
}

export function createAuthoringFixture() {
  const worlds = new Map<string, ReturnType<typeof world>>()
  function assets(id: string) {
    if (!worlds.has(id)) worlds.set(id, world())
    return worlds.get(id)!
  }
  return {
    respond(path: string, method: string, body: any, draft: (id: string) => Record<string, any>): Response | null {
      if (!path.startsWith('/adventures/')) return null
      if (path === '/adventures/editor/personality-options') return Response.json([
        { key: 'openness', label: 'Openness', options: [{ value: 'curious', label: 'Curious', help: 'Interested in unfamiliar ideas and places.' }, { value: 'cautious', label: 'Cautious', help: 'Prefers familiar approaches.' }] },
        { key: 'sociability', label: 'Sociability', options: [{ value: 'reserved', label: 'Reserved', help: 'Takes time to become comfortable with others.' }, { value: 'outgoing', label: 'Outgoing', help: 'Readily starts a conversation.' }] },
      ])
      const id = path.split('/')[2]
      if (path.endsWith('/editor/assets')) return Response.json({ adventure: draft(id), ...assets(id) })
      if (path.endsWith('/editor/entity') && method === 'PATCH') {
        const state = assets(id)
        const target = [...state.entities_all, ...state.scenes].find(entity => entity.id === body.target_id)
        if (!target) return Response.json({ detail: 'Preview entity not found.' }, { status: 404 })
        Object.assign(target, body, body.new_id ? { id: body.new_id } : {})
        Object.assign(target, { metadata_json: { ...('metadata_json' in target ? target.metadata_json as object : {}), ...body } })
        return Response.json({ status: 'saved' })
      }
      if (path.endsWith('/editor/entity') && method === 'POST') {
        const state = assets(id)
        const entity = { ...body, id: body.entity_id, current_scene_id: body.scene_id, stats: {}, inventory: body.inventory || [], equipment: {}, metadata_json: body.metadata_json || {} }
        state.entities_all.push(entity)
        if (body.entity_type === 'NPC') state.npcs.push(entity)
        else state.objects.push(entity)
        return Response.json(entity)
      }
      if (/\/editor\/(quest|award)$/.test(path) && method === 'POST') {
        const field = path.endsWith('/quest') ? 'quests' : 'awards'
        const value = draft(id)
        const entries = value[field] as Record<string, any>[]
        const key = field === 'quests' ? 'id' : 'key'
        const existing = entries.find(entry => entry[key] === body[key])
        if (existing) Object.assign(existing, body)
        else entries.push(body)
        return Response.json(body)
      }
      if (path.includes('/editor/generate-') || path.endsWith('/editor/suggest-personality') || path.endsWith('/editor/prepare-clothing')) {
        return Response.json({ detail: 'Model generation is not connected in this preview. You can edit the fictional data manually.' }, { status: 503 })
      }
      if (path.endsWith('/visual-presets')) {
        const value = draft(id)
        if (method === 'PUT') value.visual_presets = body
        return Response.json({ source: 'saved', selection: {}, presets: [], ...value.visual_presets })
      }
      if (path.endsWith('/narrator-defaults')) {
        const value = draft(id)
        if (method === 'PUT') value.narrator_defaults = body
        return Response.json({ settings: value.narrator_defaults || { voice: null, verbosity: 'default' }, voices: [] })
      }
      if (path.endsWith('/editor/validate')) return Response.json({ structural_findings: [], ai_findings: [], ai_skipped_reason: 'disabled', run_at: '2026-01-01T12:00:00Z' })
      return null
    },
  }
}
