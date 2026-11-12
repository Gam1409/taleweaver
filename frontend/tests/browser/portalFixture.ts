import { settingsService } from '../../src/services/settingsService'
import { emptyWorldBrief } from '../../src/services/worldBrief'
import type { AdventureTemplateSummary, GameSession } from '../../src/types'

const artwork = (name: string) => `${import.meta.env.BASE_URL}assets/background/${name}.jpg`
const avatar = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><rect width="80" height="80" rx="40" fill="#253247"/><text x="40" y="55" text-anchor="middle" fill="#dfc28b" font-size="44">S</text></svg>')
const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value))

export function createPortalFixture() {
  let templates: AdventureTemplateSummary[] = [
    { template_id: 'coast', title: 'Letters from the Coast', teaser: 'A forgotten letter, a quiet harbour, and a light across the water.', image_url: artwork('background5'), rule_enforcement_mode: 'rpg', selected_tone: 'Mystery', selected_image_styles: [{ id: 'watercolour', name: 'Watercolour' }], quest_count: 3, has_update: true, available_version: '1.2', version: '1.1' },
    { template_id: 'observatory', title: 'The Last Observatory', teaser: 'Follow a trail of star charts through a city above the clouds.', image_url: artwork('background4'), rule_enforcement_mode: 'story', selected_tone: 'Wonder', selected_image_styles: [{ id: 'painterly', name: 'Painterly' }], quest_count: 2, version: '1.0' },
    { template_id: 'garden', title: 'A Garden After Rain', teaser: 'An ordinary afternoon becomes a story worth remembering.', image_url: artwork('background2'), rule_enforcement_mode: 'vn', selected_tone: 'Gentle', selected_image_styles: [{ id: 'watercolour', name: 'Watercolour' }], quest_count: 1, version: '1.0' },
  ].map(item => ({ ...item, is_ready: true, creation_status: 'completed', creator: 'Demo archive', can_start: true, has_sequences: true }))
  let sessions: GameSession[] = [
    { game_id: 'coast-session', template_id: 'coast', adventure_id: 'coast', adventure_title: 'Letters from the Coast', image_url: artwork('background5'), scene_id: 'archive', current_scene_name: 'The Old Archive', in_game_time: 2160, is_paused: false, is_ready: true, avatar_id: 'Alex', status: 'active', status_note: 'Ask Mira about the lighthouse.', rule_enforcement_mode: 'rpg', selected_tone: 'Mystery', playtime_seconds: 4380, quest_count: 3, completed_quest_count: 1 },
    { game_id: 'garden-session', template_id: 'garden', adventure_id: 'garden', adventure_title: 'A Garden After Rain', image_url: artwork('background2'), scene_id: 'garden', current_scene_name: 'Winter Garden', in_game_time: 900, is_paused: true, is_ready: true, avatar_id: 'Alex', status: 'paused', status_note: '', rule_enforcement_mode: 'vn', selected_tone: 'Gentle', playtime_seconds: 1260, quest_count: 1 },
  ]
  const user = { id: 'demo-reader', username: 'Storykeeper', role: 'admin', profile_image_url: avatar, bio: 'Collector of unfinished maps and stories from the coast.', adventure_count: 2, total_xp: 240, recovery_codes_remaining: 6, default_language: 'English', earned_awards: [] }
  const settings: Record<string, any> = {
    app_version: '0.7.1-beta', keys: { openai: { masked: 'Demo provider · no real key', is_env: false } },
    is_llm_configured: true, is_t2i_configured: false,
    llm_settings: copy(settingsService.llmForm.value), t2i_settings: copy(settingsService.t2iForm.value),
    tts_settings: copy(settingsService.ttsForm.value), game_settings: copy(settingsService.gameForm.value),
    image_styles_catalog: [{ id: 'watercolour', name: 'Watercolour', description: 'Soft edges and painted light.', instruction: '' }, { id: 'painterly', name: 'Painterly', description: 'Atmospheric brushwork.', instruction: '' }],
    tone_catalog: [{ id: 'mystery', name: 'Mystery', description: 'Clues and unanswered questions.', instruction: '' }, { id: 'wonder', name: 'Wonder', description: 'A world waiting to be discovered.', instruction: '' }, { id: 'gentle', name: 'Gentle', description: 'Room to breathe.', instruction: '' }],
    available_constants: { llm_providers: [{ id: 'openai', name: 'OpenAI' }, { id: 'ollama', name: 'Ollama' }], image_providers: [{ id: 'openai', name: 'OpenAI' }], predefined_llm_models: { openai: ['demo-model'] }, predefined_image_models: {} },
  }
  const requests: string[] = [], unhandled: string[] = []
  const memory = { enabled: false, provider: 'openai', base_url: '', model: '', timeout_seconds: 30 }
  const diagnostics = { enabled: false, detailed_logging: false }
  let serial = 0
  const drafts = new Map<string, Record<string, any>>()
  function draft(id: string) {
    if (!drafts.has(id)) drafts.set(id, {
      id, title: 'New adventure', ...templates.find(t => t.template_id === id),
      plot: '', rules: '', intro_text: '', walkthrough: '', original_prompt: '',
      min_scenes: 1, max_scenes: 5, min_items: 0, max_items: 10,
      scripts: [], start_scene_id: 'archive', selected_style_id: '', selected_tone_id: '',
    })
    return drafts.get(id)!
  }
  function respond(path: string, method: string, body: any): Response {
    const json = Response.json
    requests.push(`${method} ${path}`)
    if (path === '/auth/bootstrap-status') return json({ has_admin: true, has_users: true, app_version: '0.7.1-beta', password_policy: { min_length: 8, requires_complexity: false } })
    if (path === '/auth/me') return json(user)
    if (path === '/users/me/preferences') { Object.assign(user, body); return json(user) }
    if (path === '/users/me/bio') { user.bio = body.bio; return json(user) }
    if (path === '/users/me/sessions') return json(sessions.map(s => ({ ...s, xp: 120, sequences: [], sequences_completed: 1, sequences_total: s.quest_count })))
    if (path === '/users') return json([user])
    if (path === '/adventures/templates') return json(templates)
    if (path === '/adventures/sessions') return json(sessions)
    if (path === '/settings') return json(settings)
    if (path.includes('ollama') || path.includes('stable-diffusion') || path.includes('/models')) return json({ models: [] })
    if (path === '/settings/memory-rag') { if (body) Object.assign(memory, body); return json(memory) }
    if (path === '/system-diagnostics') { if (body) Object.assign(diagnostics, body); return json(diagnostics) }
    if (path === '/inference-queue') return json({ reservations: [], endpoints: [] })
    if (path.endsWith('/memory-index')) return json({ enabled: false, status: 'disabled', session_count: 1, pending_count: 0, indexed_count: 0, paused: true })
    if (path === '/adventures/check-examples' || path === '/adventures/check-defaults') return json({ available_imports: [] })
    if (path === '/adventures/templates/update-all') { templates.forEach(t => { t.has_update = false }); return json({ updated_count: 1, updated_titles: ['Letters from the Coast'], errors: [] }) }
    if (path.startsWith('/adventures/templates/') && path.endsWith('/update')) { const item = templates.find(t => t.template_id === path.split('/')[3]); if (item) item.has_update = false; return json({ status: 'success' }) }
    if (path.startsWith('/adventures/') && method === 'DELETE') {
      const id = path.split('/').pop()
      templates = templates.filter(t => t.template_id !== id)
      sessions = sessions.filter(s => s.game_id !== id)
      return json({ status: 'deleted' })
    }
    if (path.startsWith('/adventures/sessions/') && method === 'PATCH') { const item = sessions.find(s => s.game_id === path.split('/')[3]); if (item) Object.assign(item, body); return json(item || {}) }
    if (path.endsWith('/copy')) { const item = sessions.find(s => s.game_id === path.split('/')[3]); if (item) sessions.push({ ...item, game_id: `copy-${++serial}`, adventure_title: item.adventure_title + ' (copy)' }); return json({ game_id: `copy-${serial}` }) }
    if (path.endsWith('/duplicate')) { const item = templates.find(t => t.template_id === path.split('/')[2]); if (item) templates.push({ ...item, template_id: `copy-${++serial}`, title: item.title + ' (copy)' }); return json({ adventure_id: `copy-${serial}` }) }
    if (path.endsWith('/export/adv')) return json({ title: templates.find(t => t.template_id === path.split('/')[2])?.title, description: 'Fictional preview export.' })
    if (path.endsWith('/sessions/start')) return json({ game_id: 'coast-session', template_id: path.split('/')[2], adventure_id: path.split('/')[2], avatar_id: 'Alex' })
    if (path === '/adventures/' && method === 'POST') {
      if (!body?.skip_generation) return json({ detail: 'Model generation is not connected in this preview.' }, { status: 503 })
      const id = `draft-${++serial}`
      Object.assign(draft(id), body)
      return json({ adventure_id: id, game_id: id, avatar_id: 'Alex' })
    }
    if (path.endsWith('/editor/assets')) return json({ adventure: draft(path.split('/')[2]), protagonist: null, npcs: [], objects: [], entities_all: [], scenes: [{ id: 'archive', name: 'The Old Archive', description: 'Shelves of coastal maps.', exits: [] }] })
    if (path.endsWith('/world-brief')) {
      const value = draft(path.split('/')[2])
      if (method === 'PUT') value.world_brief = body
      return json(value.world_brief || emptyWorldBrief())
    }
    if (path.endsWith('/editor/validation/latest')) return json(null)
    if (/^\/adventures\/[^/]+$/.test(path)) {
      const value = draft(path.split('/')[2])
      if (method === 'PATCH') Object.assign(value, body)
      return json(value)
    }
    if (path === '/adventures/import-examples' || path === '/adventures/reimport-defaults') return json({ status: 'success', message: 'The fictional examples are already in this preview.' })
    if (path.startsWith('/settings/') && method !== 'GET' && !path.includes('test')) {
      const section = path.split('/').pop() || ''
      const fields: Record<string, string> = { llm: 'llm_settings', t2i: 't2i_settings', tts: 'tts_settings', game: 'game_settings', tones: 'tone_catalog', 'image-styles': 'image_styles_catalog' }
      if (fields[section]) settings[fields[section]] = body?.items || body
      return json({ status: 'success', message: 'Saved in this preview only.' })
    }
    unhandled.push(`${method} ${path}`)
    return json({ detail: 'This operation needs the running application. No external request was sent.' }, { status: 501 })
  }
  return { user, requests, unhandled, respond }
}
