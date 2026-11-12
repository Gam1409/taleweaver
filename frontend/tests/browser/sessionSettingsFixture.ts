/** Browser-local responses for the session settings preview. */
export function createSessionSettingsFixture() {
  let failure = ''
  const writes: { endpoint: string; body: any }[] = []
  const narrator = { voice: null, verbosity: 'default' }
  const data: Record<string, any> = {
    'narrator-settings': narrator,
    'content-settings': { enabled: false, level: 'soft' },
    'vn-settings': { pace: 'balanced', scene_staging: false, visual_audit: true, visual_audit_failure: 'block' },
    'portrait-settings': { emotion_palette: true, character_thoughts: true, brightness: 40 },
    'dynamic-locations': { enabled: false, scale: 'auto', generate_images: false },
    'session-visual-presets': { source: 'current', selection: {}, presets: [] },
    'living-world': { living_world_enabled: false, mode: 'PAUSE', deliberation_enabled: false, decision_engine: 'native', max_deliberations: 8 },
    chpm: { mode: 'off', actor_ids: [], max_active_npcs: 3, model_role: 'complex', max_output_tokens: 1200, max_input_chars: 24000, max_calls_per_turn: 8, memory_limit: 12, agent_steps: 0, failure_policy: 'continue' },
  }
  return {
    writes,
    failSave(endpoint: string) { failure = endpoint },
    respond(path: string, method: string, body: any): Response | null {
      const key = path.split('?')[0]!.split('/').at(-1)!
      if (!(key in data)) return null
      if (method !== 'GET') writes.push({ endpoint: key, body: structuredClone(body) })
      if (method !== 'GET' && failure === key) return Response.json({ detail: 'Preview save failed. Please retry.' }, { status: 503 })
      if (method !== 'GET') data[key] = { ...data[key], ...structuredClone(body?.settings || body) }
      if (key === 'narrator-settings') return Response.json({ settings: data[key], voices: [] })
      if (key === 'vn-settings') return Response.json({ settings: data[key], available: true })
      if (key === 'dynamic-locations') return Response.json({ policy: data[key] })
      if (key === 'living-world') return Response.json({ settings: data[key], revision: 0, status: 'PAUSED', cursor: 0, target: 0, pending_events: 0, last_run_events: 0, llm_calls: 0, recap: [], concordia_available: true })
      if (key === 'chpm') return Response.json({ module_version: '1.0.0', settings: data[key], revision: 0, available: true, characters: [{ id: 'MIRA', name: 'Mira' }], usage: { status: 'idle', calls: 0 }, trace: [], memory_counts: {}, agenda_counts: { active: 0, closed: 0 }, agenda: [] })
      return Response.json(data[key])
    },
  }
}
